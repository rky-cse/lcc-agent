"""M09 durable reviewed area runs using the M03 native model integrity gate."""
import argparse
import json
from contextlib import closing
from pathlib import Path

from .areas import AreaRequest, calculate_areas
from .capture_store import FrameStore
from .contents import ContentsStore
from .models import Room, MeasurementEvidence
from .packet import json_text
from .room_measurement import verified_model, calibrated_views
from .valuation import canonical, sha


class AreaStore:
    def __init__(self, frames):
        self.frames=frames;self.contents=ContentsStore(frames)
        with closing(frames._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS area_runs (id TEXT PRIMARY KEY, request BLOB NOT NULL, result BLOB NOT NULL, sha TEXT NOT NULL)');db.commit()

    def model_path(self, request):
        relative=Path(request.reconstruction_path)
        if relative.is_absolute() or relative.drive or '..' in relative.parts:
            raise ValueError('reconstruction path must be relative inside the frame store')
        path=(self.frames.root/relative).resolve()
        if not path.is_relative_to(self.frames.root) or path==self.frames.root:
            raise ValueError('reconstruction path escapes frame store')
        return path

    def validate_shelves(self, request, inventory):
        physical={r['item']['id']:r for r in inventory['rows'] if r['item']['category']=='shelving_unit'}
        mapped={s.item_id for s in request.shelves}
        if not mapped<=set(physical):raise ValueError('shelf surfaces require current reviewed shelving-unit IDs')
        if request.shelving_coverage_complete and mapped!=set(physical):raise ValueError('complete shelving coverage omits reviewed shelving units')
        points={p.id:p for p in request.points}
        for surface in request.shelves:
            observations=physical[surface.item_id]['observations']
            for key in surface.corners:
                matched=False
                for o in points[key].observations:
                    for original in observations:
                        box=original['bounds_px']
                        if o.frame_ref==original['frame_ref'] and box[0]<=o.pixel[0]<=box[2] and box[1]<=o.pixel[1]<=box[3]:matched=True
                if not matched:raise ValueError('shelf corner lacks matching physical observation bounds')

    def get(self, run_id, sweep_id=None):
        with closing(self.frames._connect()) as db:
            row=db.execute('SELECT request,result,sha FROM area_runs WHERE id=?',(run_id,)).fetchone()
        if row is None:raise KeyError('unknown room area run')
        request=AreaRequest.model_validate_json(row[0])
        if sweep_id is not None and sweep_id!=request.sweep_id:raise KeyError('unknown room area run in this sweep')
        if sha(row[1])!=row[2]:raise ValueError('area result hash mismatch')
        result=json.loads(row[1]);source,model,records,path=verified_model(self.frames,self.model_path(request),request)
        current=self.contents.snapshot(request.sweep_id)
        result.update(result_sha256=row[2],stale=current['inventory_sha256']!=result['contents_sha256'])
        result['usable_for_current_inventory']=not result['stale'] and result['status']=='success'
        return result

    def run(self, request):
        request=AreaRequest.model_validate(request.model_dump())
        encoded=canonical(request.model_dump(mode='json'))
        with closing(self.frames._connect()) as db:
            old=db.execute('SELECT request FROM area_runs WHERE id=?',(request.run_id,)).fetchone()
        if old:
            if old[0]!=encoded:raise ValueError('run ID reused with different payload')
            return self.get(request.run_id,request.sweep_id)
        inventory=self.contents.snapshot(request.sweep_id)
        if inventory['revision']!=request.expected_contents_revision:raise ValueError('stale contents revision')
        self.validate_shelves(request,inventory)
        source,model,records,path=verified_model(self.frames,self.model_path(request),request)
        geometry=None;reason=None
        try:
            views=calibrated_views(source,model,path,records)
            geometry=calculate_areas(request,views)
        except (ValueError,ImportError) as error:reason=str(error)
        room=Room.model_validate(geometry['room']) if geometry else Room()
        fingerprint=sha(encoded);evidence=[]
        frame_refs=sorted({o.frame_ref for p in request.points for o in p.observations})
        for field,value in room.model_dump().items():
            if field not in {'length_m','width_m','height_m','floor_area_m2','wall_area_m2','shelved_wall_area_m2'} or value is None:continue
            evidence.append(MeasurementEvidence(id='area-'+fingerprint[:24]+'-'+field,ref_id='room',field=field,value=value,
                unit='m2' if field.endswith('m2') else 'm',frame_refs=frame_refs,scale_method=room.scale_method,
                derivation='Observed multiview surfaces; area_input_sha256='+fingerprint+'; reconstruction_sha256='+request.reconstruction_result_sha256))
        missing=[k for k in ('floor_area_m2','wall_area_m2','shelved_wall_area_m2') if getattr(room,k) is None]
        result=dict(schema_version='1.0',algorithm='observed-room-surfaces-v1',run_id=request.run_id,sweep_id=request.sweep_id,
            input_sha256=fingerprint,request=request.model_dump(mode='json'),contents_revision=inventory['revision'],contents_sha256=inventory['inventory_sha256'],
            status='unavailable' if reason else ('partial' if missing else 'success'),reason=reason,room=room.model_dump(),geometry=geometry,
            measurements=[e.model_dump() for e in evidence],missing_fields=missing,synthetic=any(r.synthetic for r in records.values()),
            reconstruction_request=source.model_dump(),reconstruction_artifacts=model['artifacts'],
            frames=[r.packet_evidence().model_dump() for r in records.values()],
            coverage=dict(floor_complete=request.floor_boundary_complete,openings_complete=request.openings_complete,
                shelving_complete=request.shelving_coverage_complete,physical_room_coverage_verified=False),
            warnings=['Developer annotations and reviewer completeness declarations; physical coverage is unverified.',
                'Sensitivity explores pixels and reference length separately; excludes pose, intrinsics and correspondence uncertainty.',
                'Square-foot values are rounded computational outputs; final packet integration is M10.'],packet_ready=False)
        blob=canonical(result)
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            if self.contents.snapshot(request.sweep_id)['inventory_sha256']!=inventory['inventory_sha256']:raise ValueError('contents changed during area computation')
            old=db.execute('SELECT request FROM area_runs WHERE id=?',(request.run_id,)).fetchone()
            if old:
                if old[0]!=encoded:raise ValueError('run ID reused with different payload')
            else:db.execute('INSERT INTO area_runs VALUES (?,?,?,?)',(request.run_id,encoded,blob,sha(blob)))
            db.commit()
        return self.get(request.run_id,request.sweep_id)


def main():
    parser=argparse.ArgumentParser(description='M09 reviewed observed room and shelving areas')
    parser.add_argument('--store',type=Path,required=True);parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('choose a fresh output file')
    request=AreaRequest.model_validate_json(args.input.read_text(encoding='utf-8'))
    result=AreaStore(FrameStore(args.store)).run(request)
    args.output.write_text(json_text(result)+'\n',encoding='utf-8')
    print('Room areas: '+result['status']+'; output: '+str(args.output.resolve()))


if __name__=='__main__':main()
