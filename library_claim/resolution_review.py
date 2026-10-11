"""One explicit unresolved physical observation per audited resolution."""
from contextlib import closing
from pydantic import Field, model_validator
from .guidance import Token
from .models import Contract
from .packet import json_text
from .tracking import TrackingCommand, Decision, digest
from .spine_detection import DetectionRequest, DetectionResponse, process_response


class ResolutionReview(Contract):
    review_id: Token
    session_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    expected_inventory_revision: int = Field(ge=0)
    expected_reference_revision: int = Field(ge=0)
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    decisions: list[Decision] = Field(min_length=1, max_length=1)

    @model_validator(mode='after')
    def explicit_single_resolution(self):
        if len(self.decisions) != 1 or self.decisions[0].action == 'unresolved':
            raise ValueError('Resolve exactly one observation as new or same; otherwise leave it unresolved')
        if not self.reviewer.strip() or not self.reason.strip() or not self.decisions[0].provenance.strip():
            raise ValueError('Explicit nonblank review provenance required')
        return self


class ResolutionReviewer:
    def __init__(self, guidance):
        self.guidance = guidance
        self.ledger = guidance.ledger
        self.frames = guidance.frames

    def _verify(self, state, observation_id):
        self.ledger._verify(state)
        if any(e['command_sha256'] != digest(json_text(e['command']).encode()) for e in state['events']):
            raise ValueError('resolution event integrity failure')
        obs = state['observations'].get(observation_id)
        if obs is None:
            raise KeyError('unknown observation in this session')
        source = state['imports'].get(obs['frame_ref'] + ':' + obs['shelf_id'])
        if not source or source['result_sha256'] != obs['detection_result_sha256']:
            raise ValueError('observation source integrity failure')
        request = DetectionRequest.model_validate(source['request'])
        response = DetectionResponse.model_validate(source['response'])
        result = process_response(self.frames, request, response, source['result']['provider'])
        if any(json_text(value) != json_text(source['result'].get(key)) for key, value in result.items()):
            raise ValueError('archived detection differs from validated response')
        candidate = next((p for p in result['proposals'] if p['observation_id'] == observation_id and p['status'] == 'candidate'), None)
        if (candidate is None or request.sweep_id != state['sweep_id'] or request.frame_ref != obs['frame_ref']
                or request.frame_sha256 != obs['frame_sha256'] or request.shelf_id != obs['shelf_id']
                or json_text(candidate['polygon_px']) != json_text(obs['polygon_px']) or candidate['orientation'] != obs['orientation']):
            raise ValueError('observation differs from archived detection')
        return obs

    def snapshot(self, session_id, observation_id):
        guide = self.guidance.snapshot(session_id)
        if guide['phase'] != 'capture_bound':
            raise ValueError('bind capture before resolving physical observations')
        with closing(self.frames._connect()) as db:
            state = self.ledger._read(db, session_id)
        obs = self._verify(state, observation_id)
        inventory = self.ledger._snapshot(state)
        targets = [dict(id=t['id'], shelf_id=t['shelf_id'], owned=t['owned'],
                        observations=[o for o in inventory['observations'] if o['track_id'] == t['id']])
                   for t in inventory['tracks'] if t['shelf_id'] == obs['shelf_id']]
        events = [e for e in state['events'] if e['command']['operation'] == 'resolve'
                  and any(d['observation_id'] == observation_id for d in e['command']['decisions'])]
        return dict(session_id=session_id, observation=obs, inventory_revision=state['revision'],
                    reference_revision=guide['reference_revision'], targets=targets, resolution_events=events,
                    frame=self.frames.get(obs['frame_ref']).model_dump(mode='json', include={'id','sha256','width','height','exif_orientation','synthetic'}),
                    can_resolve=obs['track_id'] is None)

    def apply(self, review):
        review = ResolutionReview.model_validate(review.model_dump())
        observation_id = review.decisions[0].observation_id
        self.snapshot(review.session_id, observation_id)  # Verify evidence even on historical retries.
        command = TrackingCommand(command_id='resolution-' + digest((review.session_id+'\0'+review.review_id).encode())[:24],
            sweep_id=review.session_id, expected_revision=review.expected_inventory_revision, operation='resolve',
            detection_result_sha256=None, decisions=review.decisions, track_id=None, owned=None,
            provenance=json_text(review.model_dump(exclude={'decisions'})))
        def guard(db, state):
            guide = self.guidance.read(db, review.session_id)
            if guide['phase'] != 'capture_bound' or guide['reference_revision'] != review.expected_reference_revision:
                raise ValueError('stale reference revision; reload before resolving')
            self._verify(state, observation_id)
        self.ledger.apply(command, guard=guard)
        with closing(self.frames._connect()) as db:
            state = self.ledger._read(db, review.session_id)
        self._verify(state, observation_id)
        event = next(e for e in state['events'] if e['command']['command_id'] == command.command_id)
        if event['command_sha256'] != digest(json_text(command.model_dump()).encode()):
            raise ValueError('resolution ledger proof differs')
        return dict(applied=True, review=review.model_dump(mode='json'), ledger_event_revision=event['revision'],
                    command_sha256=event['command_sha256'], inventory=self.ledger._snapshot(state),
                    warning='Receipt is historical; current inventory may include later reviewed changes.')
