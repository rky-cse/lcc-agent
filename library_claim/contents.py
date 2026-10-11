"""M08a: reviewed non-book physical observations, grouping and geometry proofs."""
import argparse
import json
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .capture_store import FrameStore
from .measurement import measure
from .models import Contract, Item
from .planar import MeasurementRequest
from .valuation import canonical, sha

Token = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')]
Text = Annotated[str, Field(min_length=1, max_length=2000, pattern=r'.*\S.*')]
Category = Literal['shelving_unit', 'chair', 'table', 'sofa', 'desk', 'lamp', 'rug', 'cabinet',
                   'art', 'portrait', 'mirror', 'decor', 'electronics', 'furniture_set', 'other', 'unknown']
Axis = Literal['w', 'h', 'd']


class ItemLabel(Contract):
    field: Literal['category', 'description', 'material', 'brand', 'model']
    value: Text
    basis: Literal['visible_appearance', 'visible_marking', 'claimant_assertion']
    statement: Text

    @model_validator(mode='after')
    def supported(self):
        if self.field == 'category' and self.value not in Category.__args__:
            raise ValueError('unsupported non-book category')
        if self.field in {'brand', 'model'} and self.basis != 'visible_marking':
            raise ValueError('brand/model requires reviewed literal visible marking')
        return self


class ContentsCommand(Contract):
    command_id: Token
    sweep_id: Token
    expected_revision: int = Field(ge=0)
    operation: Literal['observe', 'label', 'ownership', 'art', 'measure', 'group', 'ungroup', 'merge', 'remove']
    item_id: Token
    reviewer: Text
    reason: Text
    frame_ref: str | None = None
    frame_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    bounds_px: tuple[Annotated[float, Field(allow_inf_nan=False)],
                     Annotated[float, Field(allow_inf_nan=False)],
                     Annotated[float, Field(allow_inf_nan=False)],
                     Annotated[float, Field(allow_inf_nan=False)]] | None = None
    new_owned: bool | None = None
    labels: list[ItemLabel] = Field(default_factory=list, max_length=5)
    artwork_kind: Literal['original', 'print', 'unknown'] | None = None
    claimant_statement: str | None = Field(default=None, min_length=1, max_length=2000)
    guidance_revision: int | None = Field(default=None, ge=0)
    declaration_index: int | None = Field(default=None, ge=0)
    measurement: MeasurementRequest | None = None
    height_axis: Axis | None = None
    width_axis: Axis | None = None
    members: list[Token] = Field(default_factory=list, max_length=50)
    counting_basis: Literal['set', 'components'] | None = None
    source_item_id: Token | None = None
    proposal_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    proposal_index: int | None = Field(default=None, ge=0)
    acknowledge_historical_proposal: bool | None = None

    @model_validator(mode='after')
    def shape(self):
        allowed = dict(observe={'frame_ref', 'frame_sha256', 'bounds_px', 'new_owned', 'labels', 'proposal_sha256', 'proposal_index', 'acknowledge_historical_proposal'},
                       label={'labels', 'frame_ref', 'frame_sha256'}, ownership={'new_owned'},
                       art={'frame_ref', 'frame_sha256', 'artwork_kind', 'claimant_statement', 'guidance_revision', 'declaration_index'},
                       measure={'measurement', 'height_axis', 'width_axis'},
                       group={'members', 'counting_basis'}, ungroup=set(), merge={'source_item_id'}, remove=set())
        optional = set(type(self).model_fields)-{'command_id', 'sweep_id', 'expected_revision', 'operation', 'item_id', 'reviewer', 'reason'}
        for field in optional-allowed[self.operation]:
            if getattr(self, field) not in (None, []):
                raise ValueError('irrelevant operation field: '+field)
        if len({l.field for l in self.labels}) != len(self.labels):
            raise ValueError('duplicate label field')
        if self.operation in {'observe', 'label', 'art'} and (self.frame_ref is None or self.frame_sha256 is None):
            raise ValueError('operation requires exact saved frame and hash')
        if self.operation == 'observe' and self.bounds_px is None:
            raise ValueError('observation requires original-pixel rectangle')
        if (self.proposal_sha256 is None) != (self.proposal_index is None):
            raise ValueError('proposal hash and index must be paired')
        if self.acknowledge_historical_proposal is not None and self.proposal_sha256 is None:
            raise ValueError('historical acknowledgement requires a saved proposal')
        if self.operation == 'label' and not self.labels:
            raise ValueError('label requires at least one reviewed field')
        if self.operation == 'ownership' and self.new_owned is None:
            raise ValueError('ownership needs an explicit boolean')
        if self.operation == 'art':
            if self.artwork_kind is None or not self.claimant_statement or not self.claimant_statement.strip():
                raise ValueError('art requires explicit kind and literal claimant statement')
            if (self.guidance_revision is None) != (self.declaration_index is None):
                raise ValueError('guidance revision and declaration index must be paired')
        if self.operation == 'measure':
            if not self.measurement or self.height_axis is None or self.width_axis is None or self.height_axis == self.width_axis:
                raise ValueError('measurement needs two distinct explicit face axes')
            if self.measurement.sweep_id != self.sweep_id or len(self.measurement.spines) != 1 or self.measurement.spines[0].id != self.item_id:
                raise ValueError('measurement must target this one physical item')
        if self.operation == 'group' and (not self.members or len(set(self.members)) != len(self.members)
                                          or self.item_id in self.members or self.counting_basis is None):
            raise ValueError('group requires distinct members and explicit counting basis')
        if self.operation == 'merge' and (not self.source_item_id or self.source_item_id == self.item_id):
            raise ValueError('merge requires a different physical source item')
        return self


class ContentsStore:
    def __init__(self, frames):
        self.frames = frames
        with closing(frames._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS contents_ledgers (id TEXT PRIMARY KEY,state BLOB NOT NULL,sha TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS contents_artifacts (sha TEXT PRIMARY KEY,content BLOB NOT NULL)')
            db.commit()

    @staticmethod
    def _read(db, sweep):
        row = db.execute('SELECT state,sha FROM contents_ledgers WHERE id=?', (sweep,)).fetchone()
        if row is None:
            return dict(sweep_id=sweep, revision=0, items={}, retired={}, groups={}, events=[])
        if sha(row[0]) != row[1]:
            raise ValueError('contents ledger hash mismatch')
        return json.loads(row[0])

    def artifact(self, digest):
        with closing(self.frames._connect()) as db:
            row = db.execute('SELECT content FROM contents_artifacts WHERE sha=?', (digest,)).fetchone()
        if row is None:
            raise KeyError('unknown contents artifact')
        if sha(row[0]) != digest:
            raise ValueError('contents artifact hash mismatch')
        return row[0]

    def _verify(self, state):
        for event in state['events']:
            if event['command'].get('proposal_sha256'):
                self.artifact(event['command']['proposal_sha256'])
        for item in list(state['items'].values())+list(state['retired'].values()):
            for obs in item['observations']:
                frame = self.frames.get(obs['frame_ref'])
                if frame.sweep_id != state['sweep_id'] or frame.sha256 != obs['frame_sha256']:
                    raise ValueError('contents original frame mismatch')
            for proof in item['dimension_proofs'].values():
                self.artifact(proof['artifact_sha256'])

    def snapshot(self, sweep):
        with closing(self.frames._connect()) as db:
            state = self._read(db, sweep)
        self._verify(state)
        suppressed = set()
        for parent, group in state['groups'].items():
            suppressed.update(group['members'] if group['counting_basis'] == 'set' else [parent])
        rows = []
        for key, record in sorted(state['items'].items()):
            labels = record['labels']
            values = {k: v['value'] for k, v in labels.items()}
            category = values.get('category', '')
            if category == 'unknown':
                category = ''
            art = record.get('art')
            appraisal = (category in {'art', 'portrait'} and (art is None or art['kind'] != 'print')) or bool(art and art['kind']!='print')
            if key in state['groups'] and state['groups'][key]['counting_basis']=='set':
                for member in state['groups'][key]['members']:
                    child=state['items'][member];child_art=child.get('art')
                    child_category=child['labels'].get('category',{}).get('value','unknown')
                    if (child_category=='unknown' or not child_category
                            or child_category in {'art','portrait'} and (not child_art or child_art['kind']!='print')
                            or child_art and child_art['kind']!='print'):
                        appraisal=True
            item = Item(id=key, category=category, description=values.get('description', ''),
                        brand_model=' '.join(values.get(k, '') for k in ('brand', 'model')).strip(),
                        frame_ref=record['observations'][0]['frame_ref'], owned=record['owned'],
                        status='needs_appraisal' if appraisal else '',
                        artwork_kind=art['kind'] if art and art['kind'] in {'original', 'print'} else '',
                        dimensions_cm={axis: p['value_cm'] for axis, p in record['dimension_proofs'].items()},
                        field_evidence={k: [v['frame_ref']] for k, v in labels.items() if k in {'category','description','brand','model'}})
            item.field_evidence['brand_model']=sorted({labels[k]['frame_ref'] for k in ('brand','model') if k in labels})
            rows.append(dict(item=item.model_dump(mode='json'), material=values.get('material', ''),
                             labels=labels, observations=record['observations'], dimension_proofs=record['dimension_proofs'],
                             art=art, billable=key not in suppressed and record['owned']))
        result = dict(schema_version='1.0', sweep_id=sweep, revision=state['revision'], rows=rows,
                      groups=state['groups'], retired=state['retired'], events=state['events'],
                      reviewed_entity_count=len(rows), billable_entity_count=sum(r['billable'] for r in rows),
                      total_item_count=None, coverage_verified=False, packet_ready=False)
        result['inventory_sha256'] = sha(canonical(result))
        return result

    def apply(self, command):
        command = ContentsCommand.model_validate(command.model_dump())
        payload = command.model_dump(mode='json')
        # The exact receipt is checked before recomputation of an old geometry proof.
        with closing(self.frames._connect()) as db:
            state = self._read(db, command.sweep_id)
        self._verify(state)
        for event in state['events']:
            if event['command']['command_id'] == command.command_id:
                if event['command'] != payload:
                    raise ValueError('command ID reused with different payload')
                return self.snapshot(command.sweep_id)
        proof = None
        if command.operation == 'measure':
            proof = measure(self.frames, command.measurement)
            if proof['results'][0]['status'] != 'measured':
                raise ValueError('measurement unavailable: '+proof['results'][0]['reason'])
        frame = self.frames.get(command.frame_ref) if command.frame_ref else None
        if frame and (frame.sweep_id != command.sweep_id or frame.sha256 != command.frame_sha256):
            raise ValueError('cross-sweep or changed contents frame')
        if frame and frame.exif_orientation not in {None,1}:
            raise ValueError('contents annotations require unrotated encoded pixels')
        if command.proposal_sha256:
            artifact=json.loads(self.artifact(command.proposal_sha256))
            source=artifact.get('request',{})
            proposals=artifact.get('proposals',[])
            if (source.get('sweep_id'),source.get('frame_ref'),source.get('frame_sha256'))!=(command.sweep_id,command.frame_ref,command.frame_sha256):
                raise ValueError('proposal belongs to another original/sweep')
            if command.proposal_index>=len(proposals) or any(abs(a-b)>1e-6 for a,b in zip(proposals[command.proposal_index]['bounds_px'],command.bounds_px)):
                raise ValueError('observation differs from selected saved proposal')
            if source.get('expected_revision')!=command.expected_revision and command.acknowledge_historical_proposal is not True:
                raise ValueError('historical proposal needs explicit reviewer acknowledgement')
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read(db, command.sweep_id)
            for event in state['events']:
                if event['command']['command_id'] == command.command_id:
                    if event['command'] != payload:
                        raise ValueError('command ID reused with different payload')
                    return self.snapshot(command.sweep_id)
            if state['revision'] != command.expected_revision:
                raise ValueError('stale contents revision')
            if len(state['events']) >= 2000:
                raise ValueError('contents event limit exceeded')
            records = state['items']
            key = command.item_id
            op = command.operation
            if op == 'observe':
                x0,y0,x1,y1 = command.bounds_px
                if not 0 <= x0 < x1 < frame.width or not 0 <= y0 < y1 < frame.height:
                    raise ValueError('item rectangle outside original pixels')
                for record in records.values():
                    if any(o['frame_ref'] == frame.id and o['bounds_px'] == list(command.bounds_px) for o in record['observations']):
                        raise ValueError('exact frame region already assigned; review the existing observation')
                if key not in records:
                    if command.new_owned is None or key in state['retired']:
                        raise ValueError('new item needs explicit ownership and a fresh item ID')
                    if len(records) >= 200:
                        raise ValueError('contents item limit exceeded')
                    records[key] = dict(id=key, owned=command.new_owned, observations=[], labels={}, dimension_proofs={}, art=None)
                elif command.new_owned is not None:
                    raise ValueError('repeated view preserves ownership; use ownership operation')
                records[key]['observations'].append(dict(id=command.command_id, frame_ref=frame.id,
                     frame_sha256=frame.sha256, bounds_px=list(command.bounds_px), reviewer=command.reviewer, reason=command.reason))
            elif key not in records:
                raise KeyError('unknown physical contents item')
            record = records[key]
            if op in {'label','art'} and frame.id not in {o['frame_ref'] for o in record['observations']}:
                raise ValueError('field/assertion frame is not an observed view of this item')
            if op in {'observe','label'}:
                for label in command.labels:
                    if label.field=='category' and key in state['groups'] and label.value!='furniture_set':
                        raise ValueError('ungroup before changing a set parent category')
                    previous = record['labels'].get(label.field)
                    if op == 'observe' and previous and previous['value'] != label.value:
                        raise ValueError('repeated view cannot silently replace a reviewed field; use label review')
                    record['labels'][label.field] = dict(**label.model_dump(), frame_ref=frame.id, frame_sha256=frame.sha256,
                                                       reviewer=command.reviewer, command_id=command.command_id)
            elif op == 'ownership':
                for parent,group in state['groups'].items():
                    if key in group['members'] and group['counting_basis']=='set':
                        raise ValueError('switch to component counting or ungroup before changing one set member ownership')
                    if key==parent:
                        for member in group['members']:records[member]['owned']=command.new_owned
                record['owned'] = command.new_owned
            elif op == 'art':
                if record['labels'].get('category',{}).get('value') not in {'art','portrait'}:
                    raise ValueError('art assertion requires an art/portrait category')
                if command.guidance_revision is not None:
                    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='guidance_sessions'").fetchone():
                        raise KeyError('unknown guidance declaration')
                    row = db.execute('SELECT state FROM guidance_sessions WHERE id=?',(command.sweep_id,)).fetchone()
                    if row is None:
                        raise KeyError('unknown guidance declaration')
                    guide = json.loads(row[0]); declarations = guide.get('art_declarations',[])
                    if guide['revision'] != command.guidance_revision or command.declaration_index >= len(declarations):
                        raise ValueError('stale or missing guidance art declaration')
                    declaration = declarations[command.declaration_index]
                    if (declaration['frame_ref'],declaration['classification'],declaration['claimant_statement']) != (
                            command.frame_ref,command.artwork_kind,command.claimant_statement):
                        raise ValueError('art declaration differs from saved claimant turn')
                record['art'] = dict(kind=command.artwork_kind, claimant_statement=command.claimant_statement,
                                    frame_ref=frame.id, frame_sha256=frame.sha256, reviewer=command.reviewer,
                                    command_id=command.command_id, authenticated=False,
                                    guidance_revision=command.guidance_revision, declaration_index=command.declaration_index)
            elif op == 'measure':
                annotation = command.measurement.spines[0]
                observations = [o for o in record['observations'] if o['frame_ref'] == annotation.frame_ref]
                if not any(all(o['bounds_px'][0] <= x <= o['bounds_px'][2] and o['bounds_px'][1] <= y <= o['bounds_px'][3]
                               for x,y in annotation.corners_px) for o in observations):
                    raise ValueError('measured face is outside this item observation')
                raw = canonical(dict(command=payload, geometry=proof)); digest=sha(raw)
                db.execute('INSERT OR IGNORE INTO contents_artifacts VALUES (?,?)',(digest,raw))
                result = proof['results'][0]
                for axis,field,sensitivity in [(command.height_axis,'spine_height_cm','height'),
                                               (command.width_axis,'spine_thickness_cm','thickness')]:
                    record['dimension_proofs'][axis] = dict(value_cm=str(result[field]), frame_ref=annotation.frame_ref,
                        artifact_sha256=digest, method='verified_planar_face', sensitivity_cm=result['sensitivity_cm'][sensitivity],
                        confidence_bound=False, command_id=command.command_id)
            elif op == 'group':
                involved = {key,*command.members}
                if record['labels'].get('category',{}).get('value') != 'furniture_set':
                    raise ValueError('set parent must be explicitly classified as furniture_set')
                if any(member not in records for member in command.members):
                    raise ValueError('unknown group member')
                if command.counting_basis=='set' and any(records[m]['owned']!=record['owned'] for m in command.members):
                    raise ValueError('set counting requires consistent ownership for parent and components')
                if any(involved & {parent,*group['members']} for parent,group in state['groups'].items() if parent != key):
                    raise ValueError('overlapping/nested groups are not supported')
                state['groups'][key] = dict(members=command.members,counting_basis=command.counting_basis,
                                            reviewer=command.reviewer,command_id=command.command_id)
            elif op == 'ungroup':
                if key not in state['groups']:
                    raise ValueError('item is not a group parent')
                del state['groups'][key]
            elif op in {'merge','remove'}:
                ids = {key,command.source_item_id} if op == 'merge' else {key}
                if any(ids & {parent,*group['members']} for parent,group in state['groups'].items()):
                    raise ValueError('ungroup before merging/removing a group entity')
                source = records.get(command.source_item_id) if op == 'merge' else record
                if source is None:
                    raise KeyError('unknown merge source')
                if op == 'merge':
                    if source['owned'] != record['owned'] or any(k in record['labels'] and record['labels'][k]['value'] != v['value'] for k,v in source['labels'].items()):
                        raise ValueError('resolve conflicting ownership/labels before merging')
                    if source.get('art') and (not record.get('art') or any(source['art'][k]!=record['art'][k] for k in ('kind','claimant_statement'))):
                        raise ValueError('art declarations must be reviewed on the surviving item before merge')
                    record['observations'].extend(source['observations'])
                    # Geometry object IDs differ; do not transplant a measurement.
                    record['dimension_proofs'] = {}
                retired_id = command.source_item_id if op == 'merge' else key
                state['retired'][retired_id] = records.pop(retired_id)
                state['retired'][retired_id]['retirement'] = dict(operation=op,target=key,reason=command.reason)
            state['revision'] += 1
            state['events'].append(dict(command=payload,revision=state['revision']))
            raw = canonical(state)
            db.execute('INSERT OR REPLACE INTO contents_ledgers VALUES (?,?,?)',(command.sweep_id,raw,sha(raw)))
            db.commit()
        return self.snapshot(command.sweep_id)


def main():
    parser=argparse.ArgumentParser(description='M08 reviewed non-book physical ledger')
    parser.add_argument('--store',type=Path,required=True)
    parser.add_argument('--sweep-id',required=True)
    parser.add_argument('--command',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('choose a fresh output path')
    store=ContentsStore(FrameStore(args.store))
    if args.command:
        command=ContentsCommand.model_validate_json(args.command.read_text(encoding='utf-8'))
        if command.sweep_id!=args.sweep_id:raise ValueError('command differs from selected sweep')
        result=store.apply(command)
    else:result=store.snapshot(args.sweep_id)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(canonical(result)+b'\n')


if __name__=='__main__':main()
