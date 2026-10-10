"""Isolated optional native CPU worker. Invoked by reconstruction.py only."""

import argparse
import itertools
import json
import math
import statistics


def reconstruct(work, timeout):
    import numpy as np
    import pycolmap as pc

    if pc.__version__ != "4.2.1":
        raise RuntimeError("install the pinned PyCOLMAP 4.2.1 environment")
    database = work / "features.db"
    extraction = pc.FeatureExtractionOptions()
    extraction.num_threads = 2
    extraction.max_image_size = 1600
    extraction.sift.max_num_features = 4096
    reader = pc.ImageReaderOptions()
    reader.camera_model = "SIMPLE_RADIAL"
    calibration = json.loads((work / "request.json").read_text(encoding="utf-8")).get("camera_calibration")
    if calibration:
        reader.camera_model = "PINHOLE"
        reader.camera_params = ",".join(str(calibration[k]) for k in ("fx","fy","cx","cy"))
    pc.extract_features(database, work / "images", camera_mode=pc.CameraMode.SINGLE,
                        reader_options=reader, extraction_options=extraction, device=pc.Device.cpu)
    matching = pc.FeatureMatchingOptions()
    matching.num_threads = 2
    pc.match_exhaustive(database, matching_options=matching, device=pc.Device.cpu)
    options = pc.IncrementalPipelineOptions()
    options.num_threads = 2
    options.random_seed = 0
    options.min_model_size = 3
    options.max_num_models = 4
    options.max_runtime_seconds = timeout
    options.mapper.num_threads = 2
    if calibration:
        options.ba_refine_focal_length = False
        options.ba_refine_principal_point = False
        options.ba_refine_extra_params = False
        options.mapper.abs_pose_refine_focal_length = False
        options.mapper.abs_pose_refine_extra_params = False
    # Initialization retains native geometric defaults; no fixture tuning.
    sparse = work / "sparse"
    sparse.mkdir()
    reconstructions = pc.incremental_mapping(database, work / "images", sparse, options=options)
    summaries = []
    for model_id, model in sorted(reconstructions.items()):
        centres = {int(i): image.projection_center() for i,image in model.images.items() if image.has_pose}
        errors, angles = [], []
        for point in model.points3D.values():
            errors.append(float(point.error))
            rays = [point.xyz-centres[int(e.image_id)] for e in point.track.elements if int(e.image_id) in centres]
            pair_angles = []
            for a,b in itertools.combinations(rays,2):
                lengths = float(np.linalg.norm(a)*np.linalg.norm(b))
                if lengths > 0:
                    cosine = float(np.dot(a,b))/lengths
                    pair_angles.append(math.degrees(math.acos(max(-1,min(1,cosine)))))
            if pair_angles:
                angles.append(max(pair_angles))
        model.write_text(sparse / str(model_id))
        summaries.append(dict(model_id=int(model_id),registered_names=sorted(image.name for image in model.images.values() if image.has_pose),
            num_points3d=int(model.num_points3D()), median_reprojection_error_px=statistics.median(errors) if errors else None,
            median_triangulation_angle_deg=statistics.median(angles) if angles else None,
            camera_centres_arbitrary_units={model.images[i].name: centre.tolist() for i,centre in centres.items()}))
    result = dict(backend="pycolmap",backend_version=pc.__version__,numpy_version=np.__version__,device="cpu",
                  settings=dict(camera_model=reader.camera_model,shared_camera=True,
                                intrinsics="verified_fixed" if calibration else "estimated",threads=2,
                                feature_max_image_size=1600,max_features=4096,random_seed=0),models=summaries)
    (work / "worker-result.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def main():
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--work",type=Path,required=True)
    parser.add_argument("--timeout",type=int,required=True)
    args = parser.parse_args()
    reconstruct(args.work,args.timeout)


if __name__ == "__main__":
    main()
