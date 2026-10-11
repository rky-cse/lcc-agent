"""Local M11 delivery evidence checks. Never uploads, shares or submits."""
import argparse
from pathlib import Path

from pydantic import Field, model_validator

from .evaluation import Text, Number, Contract, digest, load_archive, read_json
from .packet import json_text


class Asset(Contract):
    path: Text
    sha256: str = Field(pattern='^[a-f0-9]{64}$')


class Demo(Contract):
    asset: Asset
    duration_s: Number
    sweep_id: Text
    packet_sha256: str
    reviewer: Text
    unedited_single_take: bool
    voice_audible: bool
    continuous_sweep: bool
    inventory_live: bool
    final_packet_visible: bool
    evidence: Text


class Setup(Contract):
    duration_s: Number
    clean_environment: bool
    success: bool
    reviewer: Text
    evidence: Asset


class Failure(Contract):
    error_id: Text
    impact: Text
    root_cause: Text
    evidence: Asset
    tried: Text
    next_two_weeks: Text


class Repair(Contract):
    metric: Text
    before_results: Text
    after_results: Text
    after_archive: Text
    heldout_results: Text
    heldout_archive: Text
    changed: Text
    reviewer: Text
    evidence: Asset


class Delivery(Contract):
    archive: Text
    second_archive: Text | None = None
    results: Text
    architecture: Asset
    demo: Demo | None
    setup: Setup | None
    failures: list[Failure] = Field(max_length=3)
    repair: Repair | None
    repo_url: str
    private_repo_asserted: bool

    @model_validator(mode='after')
    def valid(self):
        if len({f.error_id for f in self.failures}) != len(self.failures):
            raise ValueError('worst errors must be distinct observed errors')
        return self


def asset(value, base):
    path = Path(value.path)
    path = path if path.is_absolute() else base/path
    raw = path.read_bytes()
    if digest(raw) != value.sha256:
        raise ValueError('delivery asset hash mismatch: '+str(path))
    return dict(path=str(path.resolve()), sha256=value.sha256, byte_size=len(raw))


def load_results(path):
    """Verify all published evaluation artifacts, including bound truth/review."""
    root = Path(path)
    manifest = read_json(root/'evaluation-manifest.json')
    rows = manifest['files']
    if len({r['path'] for r in rows}) != len(rows):
        raise ValueError('duplicate evaluation manifest path')
    for row in rows:
        if Path(row['path']).name != row['path'] or '\\' in row['path']:
            raise ValueError('unsafe evaluation path')
        raw = (root/row['path']).read_bytes()
        if len(raw)!=row['byte_size'] or digest(raw)!=row['sha256']:
            raise ValueError('evaluation artifact changed')
    if not {'results.json','frozen-truth.json','assessment.json','evaluation.html'} <= {r['path'] for r in rows}:
        raise ValueError('incomplete evaluation artifacts')
    result = read_json(root/'results.json')
    frozen = read_json(root/'frozen-truth.json')
    assessment = read_json(root/'assessment.json')
    from .evaluation import FrozenTruth, Assessment
    frozen = FrozenTruth.model_validate(frozen)
    assessment = Assessment.model_validate(assessment)
    if result['truth_sha256']!=frozen.payload_sha256 or result['truth_sha256']!=assessment.truth_sha256 or result['packet_sha256']!=assessment.packet_sha256:
        raise ValueError('results provenance differs')
    return result


def recompute_result(result_path, archive_path):
    """A measured repair needs its packets, not just claimed metric summaries."""
    from .evaluation import FrozenTruth, Assessment, canonical, evaluate
    root = Path(result_path)
    result = load_results(root)
    packet, _, sha = load_archive(archive_path)
    if result['archive_sha256']!=sha or result['packet_sha256']!=digest(canonical(packet)):
        raise ValueError('repair archive/result differs')
    actual = evaluate(packet,FrozenTruth.model_validate(read_json(root/'frozen-truth.json')),
                      Assessment.model_validate(read_json(root/'assessment.json')))
    for field in ['metrics','scenario','acceptance_eligible','synthetic','dataset_id','sweep_id']:
        if canonical(actual[field])!=canonical(result[field]):
            raise ValueError('repair results differ from independent recomputation')
    return result


def check(spec, base):
    spec = Delivery.model_validate(spec)
    base = Path(base)
    resolve = lambda p: Path(p) if Path(p).is_absolute() else base/p
    packet, files, archive_sha = load_archive(resolve(spec.archive))
    result = load_results(resolve(spec.results))
    if result['archive_sha256'] != archive_sha:
        raise ValueError('delivery evaluation references a different archive')
    from .evaluation import canonical, evaluate, FrozenTruth, Assessment
    if result['packet_sha256'] != digest(canonical(packet)):
        raise ValueError('delivery evaluation references a different packet')
    # Recompute primary metrics rather than trusting a modified results file/manifest.
    root = resolve(spec.results)
    second = None
    if result['second_locale_status']=='recorded':
        assessment = Assessment.model_validate(read_json(root/'assessment.json'))
        if assessment.second_locale_country:
            from .evaluation import second_locale_from_archive
            second = second_locale_from_archive(packet, files, assessment)
        else:
            if not spec.second_archive:
                raise ValueError('recorded second locale needs its archive')
            second, _, second_sha = load_archive(resolve(spec.second_archive))
            if second_sha != result['second_archive_sha256']:
                raise ValueError('second-locale archive differs from evaluation')
    recomputed = evaluate(packet, FrozenTruth.model_validate(read_json(root/'frozen-truth.json')),
                          Assessment.model_validate(read_json(root/'assessment.json')), second)
    for field in ['metrics','scenario','acceptance_eligible','synthetic','dataset_id','sweep_id','errors']:
        if canonical(recomputed[field]) != canonical(result[field]):
            raise ValueError('delivery results differ from independently recomputed results')
    assets = dict(architecture=asset(spec.architecture, base))
    statuses = dict(repository='asserted' if spec.repo_url.startswith('https://') and spec.private_repo_asserted else 'not_provided',
                    architecture='present', claim_packet='integrity_checked',
                    ground_truth_results='recorded' if result['acceptance_eligible'] else 'ineligible_scenario',
                    demo='not_measured', setup='not_measured', failure_log='not_measured', measured_repair='not_measured',
                    second_locale=result['second_locale_status'])
    if spec.demo:
        d = spec.demo
        assets['demo'] = asset(d.asset, base)
        if d.sweep_id!=packet['sweep']['id'] or d.packet_sha256!=result['packet_sha256']:
            raise ValueError('demo refers to a different sweep/packet')
        statuses['demo'] = 'asserted_pass' if d.duration_s<=360 and all([d.unedited_single_take,d.voice_audible,d.continuous_sweep,d.inventory_live,d.final_packet_visible]) else 'fail'
    if spec.setup:
        s = spec.setup
        assets['setup'] = asset(s.evidence, base)
        statuses['setup'] = 'asserted_pass' if s.duration_s<900 and s.clean_environment and s.success else 'fail'
    error_ids = {e['id'] for e in result['errors']}
    for f in spec.failures:
        if f.error_id not in error_ids:
            raise ValueError('failure log references an error not observed in this evaluation')
        assets['failure_'+f.error_id] = asset(f.evidence, base)
    if len(spec.failures)==3:
        statuses['failure_log'] = 'reviewer_analysis_recorded'
    repair_comparison = None
    if spec.repair:
        r = spec.repair
        before = recompute_result(resolve(r.before_results),resolve(spec.archive))
        after = recompute_result(resolve(r.after_results),resolve(r.after_archive))
        heldout = recompute_result(resolve(r.heldout_results),resolve(r.heldout_archive))
        if before['packet_sha256'] != result['packet_sha256']:
            raise ValueError('repair before result must be this failed run')
        if before['dataset_id']!=after['dataset_id'] or before['sweep_id']==after['sweep_id']:
            raise ValueError('repair needs a fresh sweep of the failed dataset')
        if heldout['dataset_id']==before['dataset_id'] or heldout['sweep_id'] in [before['sweep_id'],after['sweep_id']]:
            raise ValueError('held-out result needs a different dataset and fresh sweep')
        if not all(v['acceptance_eligible'] and not v['synthetic'] for v in [before,after,heldout]):
            raise ValueError('repair evidence must be eligible real evaluations')
        values = [v['metrics'][r.metric] for v in [before,after,heldout]]
        if any(v['status']=='not_measured' for v in values):
            raise ValueError('repair metric is not measured')
        assets['repair'] = asset(r.evidence, base)
        repair_comparison = dict(metric=r.metric, before=values[0], after=values[1], heldout=values[2],
                                 regressions=[k for k,v in after['metrics'].items() if v['status']=='fail' and before['metrics'][k]['status']=='pass'])
        statuses['measured_repair'] = 'recorded_pass' if values[0]['status']=='fail' and values[1]['status']==values[2]['status']=='pass' else 'recorded_no_pass'
    return dict(schema_version='m11-delivery-1', sweep_id=packet['sweep']['id'], archive_sha256=archive_sha,
                statuses=statuses, assets=assets, failures=[f.model_dump() for f in spec.failures],
                repair=repair_comparison, cost=result['cost'], stage_latency=result['tables']['stages'],
                external_submission_performed=False,
                limitations=['Demo timing, editing, audible voice, live updates, private repository and clean setup are reviewer assertions; file hashes do not verify video content or remote permissions.',
                             'Root causes and repair causality require human review. No measured repair is inferred from a code change alone.'])


def main():
    parser = argparse.ArgumentParser(description='Local six-deliverable check; no external submission')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('choose fresh delivery output')
    result = check(read_json(args.input), args.input.resolve().parent)
    args.output.mkdir(parents=True)
    (args.output/'delivery.json').write_text(json_text(result)+'\n',encoding='utf-8')
    lines = ['# Actual-run failure log', '', 'Sweep: '+result['sweep_id'], '',
             'Cost completeness: '+result['cost']['status']+'. Cost ledger and stage timings: delivery.json.', '',
             '| Observed error | Impact | Root cause / evidence | Tried | Two-week next step |', '| --- | --- | --- | --- | --- |']
    for f in result['failures']:
        values = [f['error_id'],f['impact'],f['root_cause']+'; '+f['evidence']['path'],f['tried'],f['next_two_weeks']]
        lines.append('| '+' | '.join(v.replace('|','\\|').replace('\n',' ') for v in values)+' |')
    if not result['failures']:
        lines.append('| Not measured | No actual-run error analysis supplied | Pending | Pending | Pending |')
    lines += ['', 'Measured repair: '+result['statuses']['measured_repair']+'. See delivery.json for before/after/held-out values and regressions.', '',
              'This log records reviewer analysis. It does not independently establish root causes.']
    (args.output/'failure-log.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Local delivery check saved. No external submission performed.')


if __name__=='__main__':
    main()
