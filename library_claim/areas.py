"""M09 observed room surfaces; no inferred corners or catalogue dimensions."""
import math
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import Contract
from .contents import Token, Text
from .room_geometry import (ObservedPoint, MetricAnchor, ScaleCheck,
                            triangulate, dot, sub, cross, norm, unit)
from .planar import Positive


class Surface(Contract):
    id: Token
    wall_index: int = Field(ge=0, le=31)
    corners: list[Token] = Field(min_length=3, max_length=16)
    provenance: Text


class ShelfSurface(Surface):
    item_id: Token


class AreaPolicy(Contract):
    dimensions: Literal['first_edge_aligned_bounding_extents', 'unknown']
    wall_area_basis: Literal['gross', 'net']
    shelving_basis: Literal['all_reviewed_physical_shelving']
    height: Literal['constant_only', 'unknown']
    max_wall_projection_distance_m: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)]
    max_surface_plane_error_m: Annotated[float, Field(gt=0, le=.1, allow_inf_nan=False)]


class AreaGeometryPolicy(Contract):
    min_triangulation_angle_deg: Annotated[float, Field(gt=0, lt=90)]
    max_reprojection_error_px: Positive
    max_scale_check_relative_error: Annotated[float, Field(gt=0, lt=1)]
    max_sensitivity_relative_change: Annotated[float, Field(gt=0, lt=1)]


class AreaRequest(Contract):
    run_id: Token
    sweep_id: Token
    expected_contents_revision: int = Field(ge=0)
    reconstruction_path: str = Field(min_length=1, max_length=300)
    reconstruction_result_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    coordinate_space: Literal['colmap_encoded_pixels']
    annotation_source: Literal['developer_annotated']
    points: list[ObservedPoint] = Field(min_length=4, max_length=96)
    anchor: MetricAnchor
    scale_check: ScaleCheck
    floor_corners: list[Token] | None = Field(default=None, min_length=3, max_length=32)
    floor_boundary_complete: bool
    walls: list[Surface] = Field(max_length=32)
    openings: list[Surface] = Field(max_length=32)
    shelves: list[ShelfSurface] = Field(max_length=32)
    openings_complete: bool
    shelving_coverage_complete: bool
    boundary_provenance: Text
    policy: AreaGeometryPolicy
    interpretation: AreaPolicy

    @model_validator(mode='after')
    def references(self):
        ids = [p.id for p in self.points]
        if len(ids) != len(set(ids)):raise ValueError('duplicate observed point ID')
        surfaces = self.walls+self.openings+self.shelves
        groups = [self.anchor.endpoints, self.scale_check.endpoints]
        groups += ([self.floor_corners] if self.floor_corners else [])
        groups += [s.corners for s in surfaces]
        for group in groups:
            if len(group)!=len(set(group)) or not set(group)<=set(ids):
                raise ValueError('geometry requires distinct existing point references')
        boundary = set(self.floor_corners or []) | {p for s in surfaces for p in s.corners}
        if boundary & (set(self.anchor.endpoints)|set(self.scale_check.endpoints)):
            raise ValueError('reference/check points must be separate from surfaces')
        if set(self.anchor.endpoints)==set(self.scale_check.endpoints):raise ValueError('independent check reuses anchor')
        if len({s.id for s in surfaces})!=len(surfaces):raise ValueError('duplicate surface ID')
        if len({s.wall_index for s in self.walls})!=len(self.walls):raise ValueError('duplicate wall index')
        if self.floor_boundary_complete and not self.floor_corners:raise ValueError('complete floor needs observed corners')
        if self.floor_corners and any(s.wall_index>=len(self.floor_corners) for s in surfaces):raise ValueError('wall index outside floor')
        if any(not p.provenance.strip() for p in self.points) or not self.boundary_provenance.strip():
            raise ValueError('blank geometry provenance')
        return self


def rounded(value):
    if not math.isfinite(float(value)):raise ValueError('nonfinite area')
    return Decimal(str(max(0, value))).quantize(Decimal('.000001'), rounding=ROUND_HALF_EVEN)


def area_units(value):
    if value is None:return dict(m2=None, ft2=None)
    # International foot = exactly 0.3048 metre. Convert before display rounding.
    amount=Decimal(str(value))
    return dict(m2=rounded(value), ft2=(amount/Decimal('.3048')**2).quantize(Decimal('.000001'),rounding=ROUND_HALF_EVEN))


def edges(polygon):return list(zip(polygon,polygon[1:]+polygon[:1]))


def crossing(a,b,c,d):
    r=(b[0]-a[0],b[1]-a[1]);s=(d[0]-c[0],d[1]-c[1])
    determinant=r[0]*s[1]-r[1]*s[0]
    if abs(determinant)<1e-12:return None
    q=(c[0]-a[0],c[1]-a[1])
    t=(q[0]*s[1]-q[1]*s[0])/determinant
    u=(q[0]*r[1]-q[1]*r[0])/determinant
    if -1e-10<=t<=1+1e-10 and -1e-10<=u<=1+1e-10:return a[0]+t*r[0],a[1]+t*r[1]
    return None


def polygon_area(polygon):
    if any(math.dist(a,b)<1e-9 for a,b in edges(polygon)):raise ValueError('degenerate polygon edge')
    segments=edges(polygon)
    for i,(a,b) in enumerate(segments):
        for j,(c,d) in enumerate(segments):
            if j<=i or j==i+1 or (i==0 and j==len(segments)-1):continue
            if crossing(a,b,c,d) is not None:raise ValueError('self-intersecting polygon')
            # Collinear/touching non-adjacent edges must also fail.
            for p in (c,d):
                if abs((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))<1e-10 and all(min(a[k],b[k])-1e-10<=p[k]<=max(a[k],b[k])+1e-10 for k in range(2)):
                    raise ValueError('self-touching polygon')
    area=abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in segments))/2
    if area<1e-9:raise ValueError('zero polygon area')
    return area


def intervals(polygon,x):
    ys=sorted(a[1]+(x-a[0])*(b[1]-a[1])/(b[0]-a[0]) for a,b in edges(polygon) if min(a[0],b[0])<x<max(a[0],b[0]))
    if len(ys)%2:raise ValueError('invalid polygon cross-section')
    return list(zip(ys[::2],ys[1::2]))


def union_clipped(wall, polygons, holes=()):
    """Piecewise-linear vertical sweep: union intersect wall minus hole union."""
    if not polygons:return 0.0
    all_polygons=[wall]+list(polygons)+list(holes)
    for p in all_polygons:polygon_area(p)
    segments=[e for p in all_polygons for e in edges(p)]
    xs={p[0] for polygon in all_polygons for p in polygon}
    for i,(a,b) in enumerate(segments):
        for c,d in segments[i+1:]:
            point=crossing(a,b,c,d)
            if point is not None:xs.add(point[0])
    xs=sorted(xs);total=0.0
    # Between all vertex/intersection events the selected vertical length is
    # linear. Its midpoint gives the exact integral for that slab.
    for left,right in zip(xs,xs[1:]):
        if right-left<1e-10:continue
        x=(left+right)/2
        w=intervals(wall,x); ps=[span for p in polygons for span in intervals(p,x)]
        hs=[span for p in holes for span in intervals(p,x)]
        ys=sorted({v for span in w+ps+hs for v in span})
        length=0
        for low,high in zip(ys,ys[1:]):
            y=(low+high)/2
            inside=lambda spans:any(a<y<b for a,b in spans)
            if inside(w) and inside(ps) and not inside(hs):length+=high-low
        total+=(right-left)*length
    return total


def outside_distance(point, polygon):
    """Zero inside/on a polygon, otherwise Euclidean boundary distance."""
    x,y=point;inside=False;distance=math.inf
    for a,b in edges(polygon):
        dx,dy=b[0]-a[0],b[1]-a[1]
        t=max(0,min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
        distance=min(distance,math.dist(point,(a[0]+t*dx,a[1]+t*dy)))
        if (a[1]>y)!=(b[1]>y) and x<a[0]+(y-a[1])*dx/dy:inside=not inside
    return 0 if inside else distance


def surfaces(request, points, scale):
    """Metric surfaces are derived only from triangulated correspondences."""
    empty=dict(length_m=None,width_m=None,height_m=None,floor_area_m2=None,wall_area_m2=None,shelved_wall_area_m2=None)
    if not request.floor_corners:return dict(room=empty,walls=[],floor_polygon_m=None,partial=dict(floor_m2=None,gross_wall_m2=None,net_wall_m2=None,shelved_wall_m2=None))
    floor=[points[k] for k in request.floor_corners];origin=floor[0]
    u=unit(sub(floor[1],origin))
    normal=None
    for p in floor[2:]:
        vector=cross(u,sub(p,origin))
        if norm(vector)>1e-8:normal=unit(vector);break
    if normal is None:raise ValueError('degenerate floor plane')
    v=unit(cross(normal,u))
    tolerance=request.interpretation.max_surface_plane_error_m
    if any(abs(dot(sub(p,origin),normal))*scale>tolerance for p in floor):raise ValueError('floor is not planar')
    fp=[(dot(sub(p,origin),u)*scale,dot(sub(p,origin),v)*scale) for p in floor]
    floor_area=polygon_area(fp)
    # Orient the normal using observed walls, never an assumed ceiling height.
    heights=[dot(sub(points[k],origin),normal)*scale for s in request.walls for k in s.corners]
    nonzero=[h for h in heights if abs(h)>tolerance]
    if nonzero and all(h<0 for h in nonzero):normal=tuple(-x for x in normal)
    if nonzero and min(nonzero)<-tolerance and max(nonzero)>tolerance:raise ValueError('wall vertices lie on both sides of floor')
    wall_results=[];all_heights=[]
    for wall in request.walls:
        i=wall.wall_index;base=floor[i];end=floor[(i+1)%len(floor)]
        direction=unit(sub(end,base));width=norm(sub(end,base))*scale
        outward=unit(cross(direction,normal))
        def project_surface(surface,shelf=False):
            coordinates=[];offsets=[]
            for key in surface.corners:
                p=sub(points[key],base);offset=dot(p,outward)*scale
                limit=request.interpretation.max_wall_projection_distance_m if shelf else tolerance
                if abs(offset)>limit+1e-9:raise ValueError('surface too far from declared wall plane')
                offsets.append(offset);coordinates.append((dot(p,direction)*scale,dot(p,normal)*scale))
            if shelf and max(offsets)-min(offsets)>tolerance:raise ValueError('shelf front is not parallel to wall')
            polygon_area(coordinates)
            return coordinates
        wp=project_surface(wall)
        # Each wall is an elevation with its observed floor edge and a
        # piecewise-linear top; arbitrary overhangs/holes use opening polygons.
        if not math.dist(wp[0],(0,0))<=tolerance or not math.dist(wp[1],(width,0))<=tolerance:
            raise ValueError('wall must begin with matching ordered floor edge')
        top=wp[2:]
        if len(top)<2 or abs(top[0][0]-width)>tolerance or abs(top[-1][0])>tolerance or any(y<=tolerance for x,y in top) or any(x< -tolerance or x>width+tolerance for x,y in top) or any(a[0]<b[0]-tolerance for a,b in zip(top,top[1:])):
            raise ValueError('invalid observed wall top profile')
        all_heights.extend(y for x,y in top)
        holes=[project_surface(s) for s in request.openings if s.wall_index==i]
        shelves=[project_surface(s,True) for s in request.shelves if s.wall_index==i]
        gross=polygon_area(wp);opening=union_clipped(wp,holes)
        # Opening annotations must lie wholly within their own wall.
        if any(any(outside_distance(p,wp)>tolerance+1e-9 for p in h) or abs(polygon_area(h)-union_clipped(wp,[h]))>tolerance*sum(math.dist(a,b) for a,b in edges(h))+1e-7 for h in holes):raise ValueError('opening outside wall')
        net=max(0,gross-opening)
        covered=union_clipped(wp,shelves,holes if request.interpretation.wall_area_basis=='net' else ())
        wall_results.append(dict(id=wall.id,wall_index=i,polygon_m=wp,openings_m=holes,shelves_m=shelves,gross_m2=gross,net_m2=net,shelved_m2=covered,
            opening_clipping_m2=sum(max(0,polygon_area(h)-union_clipped(wp,[h])) for h in holes)))
    measured=set(s.wall_index for s in request.walls)
    if any(s.wall_index not in measured for s in request.openings+request.shelves):raise ValueError('surface refers to unmeasured wall')
    complete=request.floor_boundary_complete and measured==set(range(len(floor)))
    totals={key:sum(w[key] for w in wall_results) for key in ('gross_m2','net_m2','shelved_m2')}
    room=dict(empty)
    if request.floor_boundary_complete:
        room['floor_area_m2']=floor_area
        if request.interpretation.dimensions=='first_edge_aligned_bounding_extents':
            room.update(length_m=max(x for x,y in fp)-min(x for x,y in fp),width_m=max(y for x,y in fp)-min(y for x,y in fp))
    if complete:
        if request.interpretation.height=='constant_only' and max(all_heights)-min(all_heights)<=tolerance:
            room['height_m']=sum(all_heights)/len(all_heights)
        basis=request.interpretation.wall_area_basis
        if basis=='gross' or request.openings_complete:room['wall_area_m2']=totals[basis+'_m2']
        if request.shelving_coverage_complete and (basis=='gross' or request.openings_complete):room['shelved_wall_area_m2']=totals['shelved_m2']
    return dict(room=room,walls=wall_results,floor_polygon_m=fp,height_samples_m=all_heights,wall_boundaries_complete=complete,
        partial=dict(floor_m2=floor_area,gross_wall_m2=totals['gross_m2'] if wall_results else None,
                     net_wall_m2=totals['net_m2'] if wall_results and request.openings_complete else None,
                     shelved_wall_m2=totals['shelved_m2'] if wall_results else None))


def calculate_areas(request,views):
    points={};diagnostics={}
    for p in request.points:points[p.id],diagnostics[p.id]=triangulate(p.observations,views,request.policy)
    anchor=request.anchor;check=request.scale_check
    if not anchor.independently_verified or not anchor.provenance.strip() or not anchor.object_description.strip():raise ValueError('independently verified metric reference required')
    if not check.independently_verified or not check.provenance.strip():raise ValueError('independent metric check required')
    baseline=math.dist(*(points[k] for k in anchor.endpoints))
    if baseline<1e-8:raise ValueError('degenerate reference')
    scale=anchor.length_m/baseline
    measured=math.dist(*(points[k] for k in check.endpoints))*scale
    error=abs(measured-check.length_m)/check.length_m
    if error>request.policy.max_scale_check_relative_error:raise ValueError('independent metric check exceeds policy')
    nominal=surfaces(request,points,scale);samples=[nominal]
    for delta in (-anchor.uncertainty_m,anchor.uncertainty_m):samples.append(surfaces(request,points,(anchor.length_m+delta)/baseline))
    for p in request.points:
        if not p.corner_tolerance_px:continue
        for i,o in enumerate(p.observations):
            for axis in range(2):
                for sign in (-1,1):
                    observations=list(p.observations);pixel=list(o.pixel);pixel[axis]+=sign*p.corner_tolerance_px
                    observations[i]=o.model_copy(update={'pixel':tuple(pixel)})
                    varied=dict(points);varied[p.id],_=triangulate(observations,views)
                    b=math.dist(*(varied[k] for k in anchor.endpoints))
                    if b<1e-8:raise ValueError('reference degenerates under pixel tolerance')
                    samples.append(surfaces(request,varied,anchor.length_m/b))
    def envelope(section):
        bounds={}
        for key,value in nominal[section].items():
            if value is None:continue
            values=[sample[section][key] for sample in samples]
            if any(v is None for v in values):raise ValueError('geometry interpretation unstable under declared tolerance')
            low,high=min(values),max(values)
            if (value>0 and max(abs(low-value),abs(high-value))/value>request.policy.max_sensitivity_relative_change) or (value==0 and high>1e-6):raise ValueError('area sensitivity exceeds policy')
            bounds[key]=[rounded(low),rounded(high)]
        return bounds
    envelopes=envelope('room');partial_envelopes=envelope('partial')
    nominal.update(point_diagnostics=diagnostics,scale_m_per_model_unit=scale,check_measured_m=measured,check_relative_error=error,
                   sensitivity=envelopes,partial_sensitivity=partial_envelopes,sensitivity_method='one_at_a_time_explored_envelope',confidence_bound=False,
                   area_units={key:area_units(nominal['room'][key]) for key in ('floor_area_m2','wall_area_m2','shelved_wall_area_m2')})
    nominal['partial_area_units']={key:area_units(value) for key,value in nominal['partial'].items()}
    nominal['area_sensitivity_units']={key:[area_units(value) for value in bounds] for key,bounds in envelopes.items() if key.endswith('m2')}
    nominal['room']={key:rounded(v) if v is not None else None for key,v in nominal['room'].items()}
    nominal['room'].update(scale_method='calibrated_multiview_reference',confidence=None)
    return nominal
