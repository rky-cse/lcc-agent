import copy
import unittest
from decimal import Decimal
from pydantic import ValidationError

from library_claim.areas import AreaRequest, calculate_areas, polygon_area, union_clipped, area_units
from library_claim.room_geometry import project
from tests import test_room_geometry as upstream


def scene():
    views,points,old=upstream.scene()
    data=old.model_dump()
    data['policy'].pop('max_shape_relative_error')
    for key in ('ceiling_corners','rectangle_and_constant_height_confirmed'):data.pop(key)
    data.update(run_id='area-one',expected_contents_revision=0,reconstruction_path='models/fixture',
        floor_boundary_complete=True,walls=[dict(id=f'wall{i}',wall_index=i,corners=[f'f{i}',f'f{(i+1)%4}',f't{(i+1)%4}',f't{i}'],provenance='synthetic observed wall') for i in range(4)],
        openings=[],shelves=[],openings_complete=True,shelving_coverage_complete=True,
        interpretation=dict(dimensions='first_edge_aligned_bounding_extents',wall_area_basis='gross',shelving_basis='all_reviewed_physical_shelving',height='constant_only',max_wall_projection_distance_m=.3,max_surface_plane_error_m=.02))
    return views,points,AreaRequest.model_validate(data)


def add_polygon(request,views,coordinates,name,kind='shelves',wall=0,item='shelf1'):
    ids=[]
    for i,p in enumerate(coordinates):
        key=f'{name}-{i}';ids.append(key)
        from library_claim.room_geometry import ObservedPoint
        request.points.append(ObservedPoint(id=key,observations=[dict(frame_ref=ref,pixel=project(v,p)) for ref,v in views.items()],corner_tolerance_px=0,provenance='independent synthetic coordinates'))
    surface=dict(id=name,wall_index=wall,corners=ids,provenance='synthetic visible surface')
    if kind=='shelves':surface['item_id']=item
    data=request.model_dump();data[kind].append(surface)
    return AreaRequest.model_validate(data)


class AreasTests(unittest.TestCase):
    def setUp(self):self.views,self.points,self.request=scene()

    def result(self):return calculate_areas(self.request,self.views)

    def test_known_rectangle_and_conversion(self):
        r=self.result();room=r['room']
        for key,value in dict(length_m=3,width_m=4,height_m=2.6,floor_area_m2=12,wall_area_m2=36.4,shelved_wall_area_m2=0).items():
            self.assertAlmostEqual(float(room[key]),value,places=6)
        self.assertEqual(r['area_units']['floor_area_m2']['ft2'],Decimal('129.166925'))
        self.assertFalse(r['confidence_bound'])
        self.assertLess(r['sensitivity']['floor_area_m2'][0],12)

    def test_conversion_exact_international_foot(self):
        self.assertEqual(area_units(.09290304),dict(m2=Decimal('.092903'),ft2=Decimal('1.000000')))
        self.assertEqual(area_units(None),dict(m2=None,ft2=None))

    def test_nonrectangle_observed_polygon(self):
        # Trapezoid: parallel sides 3 and 2, perpendicular separation 4.
        for name,p in [('f2',(1,1.4,8)),('f3',(-1,1.4,8)),('t2',(1,-1.2,8)),('t3',(-1,-1.2,8))]:
            point=next(pnt for pnt in self.request.points if pnt.id==name)
            for o in point.observations:o.pixel=project(self.views[o.frame_ref],p)
        room=self.result()['room'];self.assertEqual(room['floor_area_m2'],10)
        self.assertEqual(room['length_m'],3);self.assertEqual(room['width_m'],4)

    def test_variable_height_uses_wall_profiles_without_single_height(self):
        for name in ('t2','t3'):
            point=next(p for p in self.request.points if p.id==name)
            coordinate=self.points[name];coordinate=(coordinate[0],-.6,coordinate[2])
            for o in point.observations:o.pixel=project(self.views[o.frame_ref],coordinate)
        r=self.result();self.assertIsNone(r['room']['height_m'])
        self.assertAlmostEqual(float(r['room']['wall_area_m2']),32.2,places=6)

    def test_piecewise_ceiling_profile_uses_observed_middle_vertex(self):
        from library_claim.room_geometry import ObservedPoint
        self.request.points.append(ObservedPoint(id='mid',observations=[dict(frame_ref=ref,pixel=project(v,(0,-.7,4))) for ref,v in self.views.items()],corner_tolerance_px=0,provenance='Observed synthetic dip'))
        self.request.walls[0].corners=['f0','f1','t1','mid','t0']
        r=self.result();self.assertIsNone(r['room']['height_m']);self.assertEqual(r['room']['wall_area_m2'],Decimal('35.650000'))

    def test_known_l_shaped_footprint_and_perimeter(self):
        from library_claim.room_geometry import ObservedPoint
        data=self.request.model_dump();data['points']=[p for p in data['points'] if p['id'] in {'a','b','c','d'}]
        physical=[(-1,1.4,4),(1,1.4,4),(1,1.4,5),(0,1.4,5),(0,1.4,7),(-1,1.4,7)]
        for i,p in enumerate(physical):
            for prefix,point in [('f',p),('t',(p[0],-1.2,p[2]))]:
                data['points'].append(ObservedPoint(id=f'{prefix}{i}',observations=[dict(frame_ref=ref,pixel=project(v,point)) for ref,v in self.views.items()],corner_tolerance_px=0,provenance='Independent synthetic L room').model_dump())
        data['floor_corners']=[f'f{i}' for i in range(6)]
        data['walls']=[dict(id=f'wall{i}',wall_index=i,corners=[f'f{i}',f'f{(i+1)%6}',f't{(i+1)%6}',f't{i}'],provenance='Observed L room walls') for i in range(6)]
        self.request=AreaRequest.model_validate(data);r=self.result()['room']
        self.assertEqual(r['floor_area_m2'],4);self.assertEqual(r['wall_area_m2'],26)

    def test_net_shelving_coverage_excludes_openings_without_changing_gross(self):
        self.request=add_polygon(self.request,self.views,[(-1,1.3,4.2),(1,1.3,4.2),(1,-.6,4.2),(-1,-.6,4.2)],'s')
        self.request=add_polygon(self.request,self.views,[(-.5,1.2,4),(.5,1.2,4),(.5,.2,4),(-.5,.2,4)],'o','openings')
        gross=self.result();self.assertEqual(gross['room']['shelved_wall_area_m2'],Decimal('3.800000'));self.assertEqual(gross['room']['wall_area_m2'],Decimal('36.400000'))
        self.request.interpretation.wall_area_basis='net';net=self.result()
        self.assertEqual(net['room']['shelved_wall_area_m2'],Decimal('2.800000'));self.assertEqual(net['room']['wall_area_m2'],Decimal('35.400000'))

    def test_nonplanar_floor_and_lateral_wall_rejected(self):
        point=next(p for p in self.request.points if p.id=='f2')
        for o in point.observations:o.pixel=project(self.views[o.frame_ref],(1.5,1.6,8))
        with self.assertRaisesRegex(ValueError,'floor is not planar'):self.result()
        self.views,self.points,self.request=scene();point=next(p for p in self.request.points if p.id=='t0')
        for o in point.observations:o.pixel=project(self.views[o.frame_ref],(-1.4,-1.2,4.15))
        with self.assertRaisesRegex(ValueError,'wall plane'):self.result()

    def test_explicit_unknown_dimension_choices(self):
        self.request.interpretation.dimensions='unknown';self.request.interpretation.height='unknown'
        r=self.result()['room'];self.assertIsNone(r['length_m']);self.assertIsNone(r['width_m']);self.assertIsNone(r['height_m']);self.assertEqual(r['floor_area_m2'],12)

    def test_missing_wall_preserves_known_floor_and_partial_subtotal(self):
        self.request.walls.pop();r=self.result()
        self.assertEqual(r['room']['floor_area_m2'],12);self.assertIsNone(r['room']['wall_area_m2']);self.assertIsNone(r['room']['shelved_wall_area_m2'])
        self.assertAlmostEqual(r['partial']['gross_wall_m2'],26,places=6)

    def test_incomplete_floor_never_full_area(self):
        self.request.floor_boundary_complete=False;r=self.result()
        self.assertIsNone(r['room']['floor_area_m2']);self.assertIsNone(r['room']['wall_area_m2']);self.assertAlmostEqual(r['partial']['floor_m2'],12)

    def test_no_floor_unknown_all(self):
        self.request.floor_corners=None;self.request.floor_boundary_complete=False
        self.request.walls=[];r=self.result()
        self.assertIsNone(r['room']['floor_area_m2']);self.assertIsNone(r['partial']['floor_m2'])

    def test_overlap_and_clip_shelving(self):
        self.request=add_polygon(self.request,self.views,[(-1,1.4,4.2),(.5,1.4,4.2),(.5,-.6,4.2),(-1,-.6,4.2)],'s1')
        self.request=add_polygon(self.request,self.views,[(-.5,1.4,4.2),(2,1.4,4.2),(2,-.6,4.2),(-.5,-.6,4.2)],'s2',item='shelf2')
        self.assertEqual(self.result()['room']['shelved_wall_area_m2'],5)

    def test_net_openings_overlap_deducted_once(self):
        for name,a,b in [('o1',-1,.5),('o2',-.5,1)]:
            self.request=add_polygon(self.request,self.views,[(a,1.4,4),(b,1.4,4),(b,.4,4),(a,.4,4)],name,'openings')
        self.request.interpretation.wall_area_basis='net'
        self.assertEqual(self.result()['room']['wall_area_m2'],Decimal('34.400000'))
        self.request.openings_complete=False;self.assertIsNone(self.result()['room']['wall_area_m2'])

    def test_opening_outside_wall_rejected(self):
        self.request=add_polygon(self.request,self.views,[(1,1.4,4),(1.8,1.4,4),(1.8,.4,4),(1,.4,4)],'o','openings')
        with self.assertRaisesRegex(ValueError,'opening outside'):self.result()

    def test_shelf_plane_and_offset_rejected(self):
        self.request=add_polygon(self.request,self.views,[(-1,1.4,4.5),(1,1.4,4.5),(1,-.6,4.5),(-1,-.6,4.5)],'s')
        with self.assertRaisesRegex(ValueError,'too far'):self.result()

    def test_scale_and_sensitivity_rejected(self):
        self.request.scale_check.length_m=.7
        with self.assertRaisesRegex(ValueError,'check exceeds'):self.result()
        self.request.scale_check.length_m=.5;self.request.anchor.uncertainty_m=.1
        with self.assertRaisesRegex(ValueError,'sensitivity'):self.result()

    def test_polygon_known_concave_and_self_crossed(self):
        self.assertEqual(polygon_area([(0,0),(3,0),(3,1),(1,1),(1,3),(0,3)]),5)
        for p in [[(0,0),(2,2),(0,2),(2,0)],[(0,0),(1,0),(0,0),(0,1)],[(0,0),(1,0),(2,0)]]:
            with self.subTest(p=p),self.assertRaises(ValueError):polygon_area(p)

    def test_union_crossing_triangles_and_hole(self):
        wall=[(0,0),(2,0),(2,2),(0,2)]
        a=[(0,0),(2,0),(0,2)];b=[(0,0),(2,0),(2,2)]
        self.assertAlmostEqual(union_clipped(wall,[a,b]),3)
        self.assertAlmostEqual(union_clipped(wall,[wall],holes=[[(.5,.5),(1.5,.5),(1.5,1.5),(.5,1.5)]]),3)
        self.assertEqual(union_clipped(wall,[]),0)

    def test_interpretations_and_references_required(self):
        data=self.request.model_dump()
        for update in [dict(floor_corners=['missing','f1','f2']),dict(interpretation=data['interpretation']|dict(wall_area_basis=None)),dict(walls=data['walls']*2),dict(points=data['points']*2)]:
            with self.subTest(update=update),self.assertRaises(ValidationError):AreaRequest.model_validate(data|update)


if __name__=='__main__':unittest.main()
