"""M03a: annotated, single-plane feasibility geometry. No automatic detection."""

import math
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import Contract

Finite = Annotated[float, Field(allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Point = tuple[Finite, Finite]
Quad = Annotated[list[Point], Field(min_length=4, max_length=4)]


class CheckPoint(Contract):
    pixel: Point
    plane_cm: Point
    provenance: str = Field(min_length=1)


class PlanarReference(Contract):
    id: str = Field(min_length=1)
    frame_ref: str
    frame_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    plane_id: str = Field(min_length=1)
    width_cm: Positive
    height_cm: Positive
    width_uncertainty_cm: Nonnegative
    height_uncertainty_cm: Nonnegative
    dimensions_verified: bool
    dimension_provenance: str
    corners_px: Quad  # physical (0,0), (width,0), (width,height), (0,height)
    corner_tolerance_px: Nonnegative
    coordinate_space: Literal["encoded_pixels"]
    lens_status: Literal["corrected", "verified_negligible", "unknown"]
    lens_provenance: str
    valid_region_px: Annotated[list[Point], Field(min_length=3, max_length=16)]
    validity_provenance: str
    check_points: list[CheckPoint]

    @model_validator(mode="after")
    def dimension_uncertainty(self):
        if self.width_uncertainty_cm >= self.width_cm or self.height_uncertainty_cm >= self.height_cm:
            raise ValueError("reference uncertainty must be smaller than the dimension")
        return self


class SpineAnnotation(Contract):
    id: str = Field(min_length=1)
    frame_ref: str
    plane_id: str
    corners_px: Quad  # q0-q1 thickness; q1-q2 height, also for horizontal books
    corner_tolerance_px: Nonnegative
    coplanarity_confirmed: bool
    coplanarity_provenance: str
    annotation_source: Literal["developer_annotated"]


class GeometryPolicy(Contract):
    min_reference_area_px2: Positive
    max_check_error_cm: Positive
    max_opposite_edge_relative_difference: Annotated[float, Field(gt=0, lt=1)]
    max_corner_cosine: Annotated[float, Field(gt=0, lt=1)]
    max_sensitivity_relative_change: Annotated[float, Field(gt=0, lt=1)]


class MeasurementRequest(Contract):
    sweep_id: str
    reference: PlanarReference | None
    policy: GeometryPolicy
    spines: Annotated[list[SpineAnnotation], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_spines(self):
        ids = [x.id for x in self.spines]
        if len(set(ids)) != len(ids) or "room" in ids:
            raise ValueError("spine IDs must be unique and cannot be room")
        return self


def convex(points):
    signs = []
    for i, a in enumerate(points):
        b, c = points[(i + 1) % len(points)], points[(i + 2) % len(points)]
        cross = (b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0])
        if abs(cross) < 1e-8:
            return False
        signs.append(cross > 0)
    if not all(sign == signs[0] for sign in signs):
        return False
    # All vertices must lie on the same inner side of every edge. Local turns
    # alone can incorrectly accept a self-intersecting star with >4 vertices.
    for a, b in zip(points, points[1:] + points[:1]):
        crosses = [(b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0]) for p in points]
        if any(x < -1e-8 for x in crosses) and any(x > 1e-8 for x in crosses):
            return False
    return True


def area(points):
    return abs(sum(a[0]*points[(i+1) % len(points)][1] - a[1]*points[(i+1) % len(points)][0]
                   for i, a in enumerate(points))) / 2


def inside(point, polygon):
    crosses = [(b[0]-a[0])*(point[1]-a[1]) - (b[1]-a[1])*(point[0]-a[0])
               for a, b in zip(polygon, polygon[1:] + polygon[:1])]
    return all(x >= -1e-7 for x in crosses) or all(x <= 1e-7 for x in crosses)


def multiply(a, b):
    return [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def normalize(points):
    cx, cy = (sum(p[k] for p in points)/len(points) for k in (0, 1))
    distance = sum(math.hypot(p[0]-cx, p[1]-cy) for p in points)/len(points)
    if distance < 1e-10:
        raise ValueError("degenerate reference points")
    scale = math.sqrt(2)/distance
    return [(scale*(x-cx), scale*(y-cy)) for x, y in points], [[scale,0,-scale*cx],[0,scale,-scale*cy],[0,0,1]], [[1/scale,0,cx],[0,1/scale,cy],[0,0,1]]


def fit_homography(source, width_cm, height_cm):
    if not convex(source):
        raise ValueError("reference corners must be a convex ordered quadrilateral")
    destination = [(0,0),(width_cm,0),(width_cm,height_cm),(0,height_cm)]
    src, ts, _ = normalize(source)
    dst, _, inverse_td = normalize(destination)
    matrix = []
    for (x,y), (u,v) in zip(src,dst):
        matrix.extend([[x,y,1,0,0,0,-u*x,-u*y,u],[0,0,0,x,y,1,-v*x,-v*y,v]])
    # Normalized 8x8 solve with partial pivoting. No additional numeric runtime.
    for column in range(8):
        pivot = max(range(column,8), key=lambda row:abs(matrix[row][column]))
        if abs(matrix[pivot][column]) < 1e-10:
            raise ValueError("singular or ill-conditioned reference geometry")
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        matrix[column] = [x/divisor for x in matrix[column]]
        for row in range(8):
            if row != column:
                factor = matrix[row][column]
                matrix[row] = [a-factor*b for a,b in zip(matrix[row],matrix[column])]
    values = [matrix[i][8] for i in range(8)] + [1]
    normalized = [values[i:i+3] for i in (0,3,6)]
    result = multiply(multiply(inverse_td, normalized), ts)
    if not all(math.isfinite(x) for row in result for x in row):
        raise ValueError("nonfinite homography")
    return result


def denominator(h, point):
    return h[2][0]*point[0]+h[2][1]*point[1]+h[2][2]


def transform(h, point):
    d = denominator(h,point)
    if abs(d) < 1e-9:
        raise ValueError("point is too close to projective horizon")
    result = tuple((h[i][0]*point[0]+h[i][1]*point[1]+h[i][2])/d for i in (0,1))
    if not all(math.isfinite(x) for x in result):
        raise ValueError("nonfinite transformed point")
    return result


def no_horizon(h, points):
    values = [denominator(h,p) for p in points]
    if any(abs(x) < 1e-9 for x in values) or not (all(x > 0 for x in values) or all(x < 0 for x in values)):
        raise ValueError("valid region crosses or approaches projective horizon")


def dimensions(h, corners, policy=None):
    if not convex(corners):
        raise ValueError("spine corners must be convex and ordered")
    no_horizon(h,corners)
    q = [transform(h,p) for p in corners]
    edges = [math.dist(q[i],q[(i+1)%4]) for i in range(4)]
    if min(edges) < 1e-8:
        raise ValueError("zero or degenerate spine edge")
    if policy:
        for a,b in ((edges[0],edges[2]),(edges[1],edges[3])):
            if abs(a-b)/max(a,b) > policy.max_opposite_edge_relative_difference:
                raise ValueError("rectified opposite edges disagree; plane or annotation may be invalid")
        for i in range(4):
            a,b,c = q[i-1],q[i],q[(i+1)%4]
            u,v = (a[0]-b[0],a[1]-b[1]),(c[0]-b[0],c[1]-b[1])
            cosine = abs(sum(x*y for x,y in zip(u,v)))/(math.hypot(*u)*math.hypot(*v))
            if cosine > policy.max_corner_cosine:
                raise ValueError("rectified spine is not sufficiently rectangular")
    return (edges[1]+edges[3])/2, (edges[0]+edges[2])/2


def sensitivity(reference, spine, h, nominal):
    """One-at-a-time perturbations; an explored envelope, not a confidence bound."""
    samples = [nominal]
    for dw in (-reference.width_uncertainty_cm, reference.width_uncertainty_cm):
        for dh in (-reference.height_uncertainty_cm, reference.height_uncertainty_cm):
            varied = fit_homography(reference.corners_px, reference.width_cm+dw, reference.height_cm+dh)
            samples.append(dimensions(varied,spine.corners_px))
    for original,tolerance,is_reference in [(reference.corners_px,reference.corner_tolerance_px,True),
                                           (spine.corners_px,spine.corner_tolerance_px,False)]:
        if tolerance == 0:
            continue
        for corner in range(4):
            for axis in range(2):
                for direction in (-1,1):
                    varied = [list(point) for point in original]
                    varied[corner][axis] += direction*tolerance
                    if is_reference:
                        altered = fit_homography(varied,reference.width_cm,reference.height_cm)
                        samples.append(dimensions(altered,spine.corners_px))
                    else:
                        samples.append(dimensions(h,varied))
    return [(min(s[i] for s in samples),max(s[i] for s in samples)) for i in (0,1)]


def metric(value):
    # Computational presentation precision; not a claimed physical tolerance.
    return Decimal(str(value)).quantize(Decimal("0.001"))
