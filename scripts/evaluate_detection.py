"""One-frame full-denominator polygon matching, not an end-to-end score."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_claim.spine_detection import area,intersection_polygon


def evaluate(result,truth,min_iou):
    if result["frame_sha256"]!=truth["frame_sha256"]:
        raise ValueError("truth and detection must reference the same original hash")
    predicted=[p for p in result["proposals"] if p["status"]=="candidate"]
    actual=[t for t in truth["objects"] if t["kind"]=="book_spine"]
    matrix=[]
    for p in predicted:
        row=[]
        for t in actual:
            x0,y0,x1,y1=t["box_px"]
            q=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
            intersection=intersection_polygon(p["polygon_px"],q)
            overlap=area(intersection) if len(intersection)>=3 else 0
            row.append(overlap/(area(p["polygon_px"])+area(q)-overlap))
        matrix.append(row)
    # Maximum-cardinality one-to-one matching; avoids two proposals claiming
    # one truth object, or count cancellation hiding a false positive and miss.
    matched={}
    def augment(i,seen):
        for j in sorted(range(len(actual)),key=lambda j:matrix[i][j],reverse=True):
            if matrix[i][j]<min_iou or j in seen:
                continue
            seen.add(j)
            if j not in matched or augment(matched[j],seen):
                matched[j]=i
                return True
        return False
    for i in range(len(predicted)):
        augment(i,set())
    tp=len(matched)
    return dict(synthetic=result["synthetic"],frame_sha256=result["frame_sha256"],min_iou=min_iou,
        truth_books=len(actual),candidate_books=len(predicted),true_positives=tp,false_positives=len(predicted)-tp,
        false_negatives=len(actual)-tp,precision=tp/len(predicted) if predicted else None,
        recall=tp/len(actual) if actual else None,
        matched=[dict(truth_id=actual[j]["id"],observation_id=predicted[i]["observation_id"],iou=matrix[i][j],
                      orientation_match=actual[j]["orientation"]==predicted[i]["orientation"]) for j,i in sorted(matched.items())],
        unmatched_truth=[t["id"] for j,t in enumerate(actual) if j not in matched],
        unverified="One synthetic frame does not establish actual-shelf precision/recall or cross-view count accuracy.")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--result",type=Path,required=True)
    parser.add_argument("--truth",type=Path,required=True)
    parser.add_argument("--min-iou",type=float,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if not 0<args.min_iou<=1:
        raise ValueError("IoU threshold must be in (0,1]")
    if args.output.exists():
        raise FileExistsError("choose a fresh evaluation output")
    result=evaluate(json.loads(args.result.read_text()),json.loads(args.truth.read_text()),args.min_iou)
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(f'Matched {result["true_positives"]}/{result["truth_books"]}; FP={result["false_positives"]}; FN={result["false_negatives"]}')


if __name__=="__main__":
    main()
