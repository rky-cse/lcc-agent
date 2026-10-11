"""M03b2 pure geometry: developer observations, metric anchor, rectangle gate."""

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import Contract
from .planar import Nonnegative, Point, Positive


class Observation(Contract):
    frame_ref: str
    pixel: Point


class ObservedPoint(Contract):
    id: str = Field(min_length=1)
    observations: Annotated[list[Observation], Field(min_length=2, max_length=12)]
    corner_tolerance_px: Nonnegative
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_views(self):
        refs = [o.frame_ref for o in self.observations]
        if len(set(refs)) != len(refs):
            raise ValueError("point observations need distinct views")
        return self


class MetricAnchor(Contract):
    object_description: str = Field(min_length=1)
    endpoints: tuple[str,str]
    length_m: Positive
    uncertainty_m: Nonnegative
    independently_verified: bool
    provenance: str

    @model_validator(mode="after")
    def dimension_valid(self):
        if self.uncertainty_m >= self.length_m or self.endpoints[0] == self.endpoints[1]:
            raise ValueError("anchor uncertainty/endpoints invalid")
        return self


class ScaleCheck(Contract):
    endpoints: tuple[str,str]
    length_m: Positive
    independently_verified: bool
    provenance: str = Field(min_length=1)


class RoomPolicy(Contract):
    min_triangulation_angle_deg: Annotated[float, Field(gt=0, lt=90)]
    max_reprojection_error_px: Positive
    max_scale_check_relative_error: Annotated[float, Field(gt=0, lt=1)]
    max_shape_relative_error: Annotated[float, Field(gt=0, lt=1)]
    max_sensitivity_relative_change: Annotated[float, Field(gt=0, lt=1)]


class RoomRequest(Contract):
    sweep_id: str = Field(min_length=1)
    reconstruction_result_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    coordinate_space: Literal["colmap_encoded_pixels"]
    annotation_source: Literal["developer_annotated"]
    points: Annotated[list[ObservedPoint], Field(min_length=1, max_length=20)]
    anchor: MetricAnchor | None
    scale_check: ScaleCheck | None
    floor_corners: tuple[str,str,str,str] | None
    ceiling_corners: tuple[str,str,str,str] | None
    rectangle_and_constant_height_confirmed: bool
    boundary_provenance: str
    policy: RoomPolicy

    @model_validator(mode="after")
    def references(self):
        ids = [p.id for p in self.points]
        if len(ids) != len(set(ids)):
            raise ValueError("point IDs must be unique")
        for group in ([self.anchor.endpoints] if self.anchor else []) + ([self.scale_check.endpoints] if self.scale_check else []) + ([self.floor_corners] if self.floor_corners else []) + ([self.ceiling_corners] if self.ceiling_corners else []):
            if len(set(group)) != len(group) or any(x not in ids for x in group):
                raise ValueError("dimension/boundary references need distinct existing point IDs")
        boundary = set((self.floor_corners or ())+(self.ceiling_corners or ()))
        if any(boundary.intersection(group) for group in ([self.anchor.endpoints] if self.anchor else [])+([self.scale_check.endpoints] if self.scale_check else [])):
            raise ValueError("reference/check points must be separate from room boundary points")
        return self


def dot(a,b):
    return sum(x*y for x,y in zip(a,b))


def sub(a,b):
    return tuple(x-y for x,y in zip(a,b))


def norm(a):
    return math.sqrt(dot(a,a))


def unit(a):
    length = norm(a)
    if length < 1e-12:
        raise ValueError("degenerate vector")
    return tuple(x/length for x in a)


def cross(a,b):
    return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


def solve3(matrix,rhs):
    rows = [list(row)+[value] for row,value in zip(matrix,rhs)]
    for col in range(3):
        pivot = max(range(col,3),key=lambda i:abs(rows[i][col]))
        if abs(rows[pivot][col]) < 1e-10:
            raise ValueError("singular triangulation; translation/parallax insufficient")
        rows[col],rows[pivot] = rows[pivot],rows[col]
        rows[col] = [x/rows[col][col] for x in rows[col]]
        for row in range(3):
            if row != col:
                factor = rows[row][col]
                rows[row] = [a-factor*b for a,b in zip(rows[row],rows[col])]
    result = tuple(row[3] for row in rows)
    if not all(math.isfinite(x) for x in result):
        raise ValueError("nonfinite triangulation")
    return result


def project(view,point):
    camera = tuple(dot(row,point)+t for row,t in zip(view["R"],view["t"]))
    if camera[2] <= 1e-8:
        raise ValueError("point is behind a camera")
    return (view["fx"]*camera[0]/camera[2]+view["cx"],view["fy"]*camera[1]/camera[2]+view["cy"])


def triangulate(observations,views,policy=None):
    matrix, rhs, rays = [[0.0]*3 for _ in range(3)], [0.0]*3, []
    for observation in observations:
        view = views.get(observation.frame_ref)
        if view is None:
            raise ValueError("annotation view is outside the connected model")
        x,y = observation.pixel
        if not (0 <= x < view["width"] and 0 <= y < view["height"]):
            raise ValueError("annotation is outside encoded image bounds")
        transpose = list(zip(*view["R"]))
        centre = tuple(-dot(row,view["t"]) for row in transpose)
        camera_ray = ((x-view["cx"])/view["fx"],(y-view["cy"])/view["fy"],1)
        ray = unit(tuple(dot(row,camera_ray) for row in transpose))
        rays.append(ray)
        projection = [[float(i==j)-ray[i]*ray[j] for j in range(3)] for i in range(3)]
        for i in range(3):
            rhs[i] += dot(projection[i],centre)
            for j in range(3):
                matrix[i][j] += projection[i][j]
    point = solve3(matrix,rhs)
    angles = [math.degrees(math.acos(max(-1,min(1,dot(a,b))))) for i,a in enumerate(rays) for b in rays[i+1:]]
    maximum_angle = max(angles)
    errors = [math.dist(project(views[o.frame_ref],point),o.pixel) for o in observations]
    if policy:
        if maximum_angle < policy.min_triangulation_angle_deg:
            raise ValueError("point has insufficient triangulation angle")
        if max(errors) > policy.max_reprojection_error_px:
            raise ValueError("point reprojection error exceeds policy")
    return point,dict(max_triangulation_angle_deg=maximum_angle,max_reprojection_error_px=max(errors))


def room_dimensions(points,request,scale):
    if not request.rectangle_and_constant_height_confirmed or not request.boundary_provenance.strip():
        raise ValueError("rectangular floor/constant height boundary validity is unconfirmed")
    if request.floor_corners is None or request.ceiling_corners is None:
        raise ValueError("floor and matching ceiling corners are incomplete")
    floor = [points[x] for x in request.floor_corners]
    ceiling = [points[x] for x in request.ceiling_corners]
    edges = [sub(floor[(i+1)%4],floor[i]) for i in range(4)]
    lengths = [norm(e) for e in edges]
    if min(lengths) < 1e-8:
        raise ValueError("degenerate floor edge")
    tolerance = request.policy.max_shape_relative_error
    for i in range(4):
        if abs(dot(unit(edges[i]),unit(edges[(i+1)%4]))) > tolerance:
            raise ValueError("observed floor is not rectangular")
    for a,b in ((lengths[0],lengths[2]),(lengths[1],lengths[3])):
        if abs(a-b)/max(a,b) > tolerance:
            raise ValueError("opposite floor edges disagree")
    normal = unit(cross(edges[0],edges[1]))
    diagonal = max(lengths)
    if max(abs(dot(sub(p,floor[0]),normal)) for p in floor)/diagonal > tolerance:
        raise ValueError("floor points are not coplanar")
    vectors = [sub(top,bottom) for top,bottom in zip(ceiling,floor)]
    heights = [dot(v,normal) for v in vectors]
    if min(heights) < 0 and max(heights) < 0:
        heights = [-h for h in heights]
    if min(heights) <= 1e-8:
        raise ValueError("ceiling corners do not share a positive floor-normal height")
    for vector,height in zip(vectors,heights):
        if math.sqrt(max(0,norm(vector)**2-height**2))/height > tolerance:
            raise ValueError("ceiling corners are not above their matching floor corners")
    if (max(heights)-min(heights))/max(heights) > tolerance:
        raise ValueError("observed ceiling height is not constant")
    return ((lengths[0]+lengths[2])/2*scale,(lengths[1]+lengths[3])/2*scale,sum(heights)/4*scale)


def calculate_room(request,views):
    """All-or-unknown narrow feasibility result; does not fit a hidden rectangle."""
    points, diagnostics = {}, {}
    for annotated in request.points:
        if not annotated.provenance.strip():
            raise ValueError("point correspondence has no provenance")
        points[annotated.id],diagnostics[annotated.id] = triangulate(annotated.observations,views,request.policy)
    anchor = request.anchor
    if anchor is None or not anchor.independently_verified or not anchor.provenance.strip() or not anchor.object_description.strip():
        raise ValueError("no independently verified metric reference")
    a,b = anchor.endpoints
    baseline = math.dist(points[a],points[b])
    if baseline < 1e-8:
        raise ValueError("degenerate metric anchor")
    scale = anchor.length_m/baseline
    check = request.scale_check
    if check is None or not check.independently_verified or not check.provenance.strip() or set(check.endpoints)==set(anchor.endpoints):
        raise ValueError("independent metric check is missing or reuses the fitted anchor")
    check_value = math.dist(*(points[x] for x in check.endpoints))*scale
    check_error = abs(check_value-check.length_m)/check.length_m
    if check_error > request.policy.max_scale_check_relative_error:
        raise ValueError("independent metric check exceeds policy")
    nominal = room_dimensions(points,request,scale)
    samples = [nominal]
    for delta in (-anchor.uncertainty_m,anchor.uncertainty_m):
        samples.append(room_dimensions(points,request,(anchor.length_m+delta)/baseline))
    # Coordinate errors explored separately, including anchor endpoint movement.
    for annotated in request.points:
        if annotated.corner_tolerance_px == 0:
            continue
        for i,observation in enumerate(annotated.observations):
            for axis in range(2):
                for sign in (-1,1):
                    varied = list(annotated.observations)
                    pixel = list(observation.pixel)
                    pixel[axis] += sign*annotated.corner_tolerance_px
                    varied[i] = observation.model_copy(update={"pixel":tuple(pixel)})
                    changed = dict(points)
                    changed[annotated.id],_ = triangulate(varied,views)
                    altered_baseline = math.dist(changed[a],changed[b])
                    if altered_baseline < 1e-8:
                        raise ValueError("anchor degenerates under declared pixel tolerance")
                    samples.append(room_dimensions(changed,request,anchor.length_m/altered_baseline))
    envelope = [(min(s[i] for s in samples),max(s[i] for s in samples)) for i in range(3)]
    if any(max(abs(low-v),abs(high-v))/v > request.policy.max_sensitivity_relative_change
           for (low,high),v in zip(envelope,nominal)):
        raise ValueError("declared annotation/reference sensitivity exceeds policy")
    return dict(dimensions_m=nominal,scale_m_per_model_unit=scale,check_measured_m=check_value,
                check_relative_error=check_error,points_arbitrary_units=points,point_diagnostics=diagnostics,
                sensitivity_m=envelope,sensitivity_method="one_at_a_time_explored_envelope",confidence_bound=False)
