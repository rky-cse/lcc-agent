import copy
import unittest

from pydantic import ValidationError

from library_claim.room_geometry import RoomRequest, calculate_room, project, triangulate


def scene():
    views = {f"v{i}":dict(R=[[1,0,0],[0,1,0],[0,0,1]],t=[-x,0,0],
        fx=1200,fy=1200,cx=960,cy=540,width=1920,height=1080) for i,x in enumerate([-1.2,0,1.2])}
    points = {"a":(-.5,-.8,4),"b":(.5,-.8,4),"c":(-.5,-.3,4),"d":(.5,-.3,4)}
    floor = [(-1.5,1.4,4),(1.5,1.4,4),(1.5,1.4,8),(-1.5,1.4,8)]
    for i,p in enumerate(floor):
        points[f"f{i}"] = p
        points[f"t{i}"] = (p[0],-1.2,p[2])
    request = RoomRequest(sweep_id="fixture",reconstruction_result_sha256="0"*64,
        coordinate_space="colmap_encoded_pixels",annotation_source="developer_annotated",
        points=[dict(id=name,observations=[dict(frame_ref=ref,pixel=project(view,p)) for ref,view in views.items()],
                     corner_tolerance_px=.1,provenance="independent synthetic observations") for name,p in points.items()],
        anchor=dict(object_description="synthetic 1 x .5 m reference",endpoints=["a","b"],length_m=1,uncertainty_m=.001,
                    independently_verified=True,provenance="synthetic reference width"),
        scale_check=dict(endpoints=["a","c"],length_m=.5,independently_verified=True,provenance="independent reference height"),
        floor_corners=[f"f{i}" for i in range(4)],ceiling_corners=[f"t{i}" for i in range(4)],
        rectangle_and_constant_height_confirmed=True,boundary_provenance="synthetic observed corners",
        policy=dict(min_triangulation_angle_deg=2,max_reprojection_error_px=2,max_scale_check_relative_error=.03,
                    max_shape_relative_error=.03,max_sensitivity_relative_change=.05))
    return views,points,request


class RoomGeometryTests(unittest.TestCase):
    def setUp(self):
        self.views,self.points,self.request = scene()

    def test_independent_room_dimensions(self):
        result = calculate_room(self.request,self.views)
        for actual,expected in zip(result["dimensions_m"],(3,4,2.6)):
            self.assertAlmostEqual(actual,expected,places=8)
        self.assertAlmostEqual(result["scale_m_per_model_unit"],1)
        self.assertFalse(result["confidence_bound"])

    def test_triangulation_recovers_observed_point(self):
        point,diagnostics = triangulate(self.request.points[0].observations,self.views,self.request.policy)
        for actual,expected in zip(point,self.points["a"]):
            self.assertAlmostEqual(actual,expected,places=8)
        self.assertLess(diagnostics["max_reprojection_error_px"],1e-8)

    def test_similarity_translation_scale_invariance(self):
        altered = copy.deepcopy(self.views)
        offset = [3,-2,1]
        for view in altered.values():
            centre = [-x for x in view["t"]]
            view["t"] = [-(c*7+o) for c,o in zip(centre,offset)]
        result = calculate_room(self.request,altered)
        for actual,expected in zip(result["dimensions_m"],(3,4,2.6)):
            self.assertAlmostEqual(actual,expected,places=8)
        self.assertAlmostEqual(result["scale_m_per_model_unit"],1/7)

    def test_missing_or_unverified_anchor_rejected(self):
        self.request.anchor = None
        with self.assertRaisesRegex(ValueError,"reference"):
            calculate_room(self.request,self.views)
        _,_,self.request = scene()
        self.request.anchor.independently_verified = False
        with self.assertRaisesRegex(ValueError,"reference"):
            calculate_room(self.request,self.views)

    def test_independent_check_required(self):
        self.request.scale_check = None
        with self.assertRaisesRegex(ValueError,"check"):
            calculate_room(self.request,self.views)

    def test_check_reuse_rejected(self):
        self.request.scale_check.endpoints = ("b","a")
        with self.assertRaisesRegex(ValueError,"reuses"):
            calculate_room(self.request,self.views)

    def test_wrong_metric_check_rejected(self):
        self.request.scale_check.length_m = .7
        with self.assertRaisesRegex(ValueError,"check exceeds"):
            calculate_room(self.request,self.views)

    def test_low_parallax_rejected(self):
        views = copy.deepcopy(self.views)
        for view in views.values():
            view["t"] = [0,0,0]
        with self.assertRaises(ValueError):
            calculate_room(self.request,views)

    def test_bad_correspondence_rejected(self):
        point = self.request.points[0]
        point.observations[0].pixel = (point.observations[0].pixel[0],point.observations[0].pixel[1]+20)
        with self.assertRaisesRegex(ValueError,"reprojection"):
            calculate_room(self.request,self.views)

    def test_out_of_bounds_and_unknown_view_rejected(self):
        self.request.points[0].observations[0].pixel = (-1,100)
        with self.assertRaisesRegex(ValueError,"bounds"):
            calculate_room(self.request,self.views)
        _,_,self.request = scene()
        self.request.points[0].observations[0].frame_ref = "not-connected"
        with self.assertRaisesRegex(ValueError,"connected model"):
            calculate_room(self.request,self.views)

    def test_boundary_assertions_and_completeness_required(self):
        self.request.rectangle_and_constant_height_confirmed = False
        with self.assertRaisesRegex(ValueError,"unconfirmed"):
            calculate_room(self.request,self.views)
        _,_,self.request = scene()
        self.request.ceiling_corners = None
        with self.assertRaisesRegex(ValueError,"incomplete"):
            calculate_room(self.request,self.views)

    def change_point(self,name,physical):
        point = next(p for p in self.request.points if p.id==name)
        for observation in point.observations:
            observation.pixel = project(self.views[observation.frame_ref],physical)

    def test_nonrectangular_floor_rejected(self):
        self.change_point("f2",(1.1,1.4,8))
        with self.assertRaisesRegex(ValueError,"rectangular|opposite"):
            calculate_room(self.request,self.views)

    def test_varying_or_lateral_ceiling_rejected(self):
        for point in [(1.5,-.8,8),(1.8,-1.2,8)]:
            with self.subTest(point=point):
                _,_,self.request = scene()
                self.change_point("t2",point)
                with self.assertRaisesRegex(ValueError,"height|above"):
                    calculate_room(self.request,self.views)

    def test_uncertainty_gate(self):
        self.request.anchor.uncertainty_m = .1
        with self.assertRaisesRegex(ValueError,"sensitivity"):
            calculate_room(self.request,self.views)

    def test_schema_ids_uncertainty_and_nonfinite(self):
        for update in [dict(points=self.request.model_dump()["points"]*2),
                       dict(floor_corners=["missing","f1","f2","f3"]),
                       dict(anchor=self.request.anchor.model_dump()|dict(uncertainty_m=1)),
                       dict(anchor=self.request.anchor.model_dump()|dict(length_m=float("inf")))]:
            with self.subTest(update=update),self.assertRaises(ValidationError):
                RoomRequest.model_validate(self.request.model_dump()|update)


if __name__=="__main__":
    unittest.main()
