"""Read-only reconstruction of retained research runs; never executes a runner."""
from pathlib import Path
from collections import Counter, defaultdict
import cmath
import csv
import datetime as dt
import hashlib
import json
import argparse
import logging
import sys
import math
import statistics

# This parser reconstructs the retained historical dataset. It is not the schema
# for future experiments. No simulator, QPU runtime or network client is imported.
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1],
                    help="Checkout containing the pinned historical data (default: this script's repository).")
parser.add_argument('--output', type=Path, help='Write JSON here; omit to write JSON to stdout.')
parser.add_argument('--metrics-output', type=Path, help='Optional compact existing-data arithmetic JSON.')
args = parser.parse_args()
SRC = args.repo_root.resolve()
CATALOGUED_ON = '2026-11-10'
logger = logging.getLogger('historical_run_inventory')
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
EXPECTED_SOURCE_SHA256 = {
  "data/qpu/ablation_block_counts.json": "b1b4f3a1e51fe9033bbfdc78930d0df7527a62c0c310fc27e81cf4969fe84469",
  "data/qpu/ablation_block_run_meta.json": "002495a22913989675d56f7746fb2c817ee7e3643d8af2513e9ad8e30e88ed16",
  "data/qpu/ablation_interleaved_counts.json": "b9b0cb874e196b5171419c4756a69543e1fbea2555c27002638deb64f26037de",
  "data/qpu/ablation_interleaved_run_meta.json": "eb1cbc3b80fd63c1c18d53a058b4f6dd968d5ac517404dbcb1ee7b6957a91101",
  "data/qpu/qpu_counts.json": "c9ac526aa50e42335749049b338dd6e341d0a3189a4450a99ac03ebd9510bae0",
  "data/qpu/qpu_run_meta.json": "01cddbf79c380eabb824a71ca00099a0ec604da272ede053de50a41013c3ccc8",
  "data/sim/grid_BFS_Shell_rows.csv": "b0b091c0c7690c4906eeb68eeef038998a6b6e791a9a384655e4c0b2f4314f4f",
  "data/sim/grid_BFS_Shell_run_meta.json": "712c8729095210bb4032dbdfb1eb6014dab76345f7dde5aba05c3074c6e6213b",
  "data/sim/grid_BFS_Shell_stats_meta.json": "411f01c937bb6aa4c341de3085e186d9d195562acaf1752a4f3ba604ef4b4df2",
  "data/sim/grid_BFS_Shell_trial_summary.csv": "966d7d6ddd0d2a2134e509bbc910fe6d26fe047f7b3377f2994eaa4cf6726ca0",
  "src/qpu/ibm_fez_full_20251231_220523.json": "9a36cbca831059af718f6b267577abfe49c4ec30a2b3c0fd81c1c69e341b5881",
  "src/qpu/model_provider.py": "d09081480a9a4962b8ca205a2d606217ebac36587d1d8cf4d0305b4d4919bf25",
  "src/qpu/models_ibm_fez_eta00/diagonal_model_ibm_fez_subgraph_n2.yaml": "b4742caf2b652daf4732665a1bccdaa8436a77ece61380ad256dbb53a6db1f9d",
  "src/qpu/models_ibm_fez_eta00/diagonal_model_ibm_fez_subgraph_n3.yaml": "8561316b1de3f6441db3cf654806935683ed50d2ed2fc4cefe958107c511042b",
  "src/qpu/models_ibm_fez_eta00/diagonal_model_ibm_fez_subgraph_n4.yaml": "ea6072882cdb2e218d21b402ccc0234451356680451091a66eaaeb5b57099c9c",
  "src/qpu/models_ibm_fez_eta00/diagonal_model_ibm_fez_subgraph_n5.yaml": "dee9303423ff77efbc1a75920f8c779a55b09d34a89bc120619b1a3950521eaf",
  "src/qpu/models_ibm_fez_eta00/diagonal_model_ibm_fez_subgraph_n6.yaml": "237a1ad4adde26f75c4058a24d20feb6cbccc4dd7abdbdce28a9bd66b2f708d9",
  "src/qpu/models_ibm_fez_eta00/diagonal_model_ibm_fez_subgraph_n7.yaml": "4359ff532c5445e09587c521451fd316fc59d0713dfef622f120378fd9600a58",
  "src/qpu/models_ibm_fez_eta01/diagonal_model_ibm_fez_subgraph_n2.yaml": "50c48be83bc5b27a985999b778d32faedb9581ab52dd831e12688be2be942b70",
  "src/qpu/models_ibm_fez_eta01/diagonal_model_ibm_fez_subgraph_n3.yaml": "fa2bf4848eb98efbaa2ab82361d900acff70611188a0afd7bcdade33c5a21606",
  "src/qpu/models_ibm_fez_eta01/diagonal_model_ibm_fez_subgraph_n4.yaml": "7fb25176d70b758127d8bd15beeb892ce597d49a3eb6ea131ef49b3bc9996bc4",
  "src/qpu/models_ibm_fez_eta01/diagonal_model_ibm_fez_subgraph_n5.yaml": "21448e202483bdf2099dce769e65d132cc035209eacd21c0ce9677c3fcf66f7e",
  "src/qpu/models_ibm_fez_eta01/diagonal_model_ibm_fez_subgraph_n6.yaml": "d54f678acb53169ba6bf3b4c31f7477c25323393c5ef015b43c3bfa4ec179bbf",
  "src/qpu/models_ibm_fez_eta01/diagonal_model_ibm_fez_subgraph_n7.yaml": "f38509449a0f090472f88a7399d9dbb3a8898b35f5ad3665747d6b3e01017997",
  "src/qpu/models_ibm_fez_eta02/diagonal_model_ibm_fez_subgraph_n2.yaml": "51e83a0690e61d47fc2597f501669a7cc6c6c8339013ef68248688b49594c771",
  "src/qpu/models_ibm_fez_eta02/diagonal_model_ibm_fez_subgraph_n3.yaml": "d2cbf150680494bf05888935f6e29ac1c1de8d4b8aeb32ec2bba6b04f340f8de",
  "src/qpu/models_ibm_fez_eta02/diagonal_model_ibm_fez_subgraph_n4.yaml": "b996532eb17118a8f0f20d2c042efb7b0341ffcb90f5b8ef3909eff54e554466",
  "src/qpu/models_ibm_fez_eta02/diagonal_model_ibm_fez_subgraph_n5.yaml": "9064d00368ef8a4a99b887ca40fa6bb413bc8abe6052718b0799e87e3d265c8a",
  "src/qpu/models_ibm_fez_eta02/diagonal_model_ibm_fez_subgraph_n6.yaml": "fa4a8b66da7f38c773941c686ae615a6333fccc78f7e08eed867c20f4485478d",
  "src/qpu/models_ibm_fez_eta02/diagonal_model_ibm_fez_subgraph_n7.yaml": "08d15db186ae6051dddfb8bc09d16615ee00cbcf21ade8bfb0bdb58d1b0cd372",
  "src/qpu/qiskit_runner.py": "598155a7e84e9e35c2c22e6fdeb1bbb28e6a8355e195effca403f67e4c03e5a6",
  "src/qpu/qiskit_runner.yaml": "8a1c6cd139cdaa11dee72cae414cb93dde1cb74ba6ed07f296f7f1dc2c2da8c8",
  "src/qpu/qiskit_runner_two_pairs.py": "553934b7fb401c3ea692ede2b7a5f319c0c443fcd513489177280827b6233e9c",
  "src/qpu/qiskit_runner_two_pairs.yaml": "e4c1cfdd755c189b88f3b462c6e04138263707c1b51e3d28641550953ab5c3b4",
  "src/qpu/qiskit_runner_two_pairs_block.py": "070a4d5fb6c9bbf09d88853b5dfc25c009d936868df0022f2e7691469c3410bf",
  "src/sim/model_provider.py": "d09081480a9a4962b8ca205a2d606217ebac36587d1d8cf4d0305b4d4919bf25",
  "src/sim/sim_runner.py": "60b8080d2ceb6a4f6a1cf772704fa4c512282c75b9ba0e50d585fe097543674d",
  "src/sim/sim_runner.yaml": "6d096ab1eb36c8e89c82034bd8a72fe587801997a86af0af25a2b5b6a287d313",
  "src/sim/stats.py": "0d10929b3c354257ef2d9619966d798ec7e31dd829dc962b0b194b12f510bb9b"
}
SETTINGS = ['cos_a', 'sin_a', 'cos_b', 'sin_b']
errors = []

def check(condition, message):
    if not condition:
        errors.append(message)

def read_json(path):
    return json.loads((SRC / path).read_bytes())

def read_csv(path):
    with (SRC / path).open(encoding='utf-8-sig', newline='') as fh:
        return list(csv.DictReader(fh))

def digest(path):
    raw = (SRC / path).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    check(actual == EXPECTED_SOURCE_SHA256.get(path), f'Historical source hash mismatch: {path}')
    return {'path': path, 'bytes': len(raw), 'sha256': actual,
            'git_blob_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def quantile(xs, q):
    xs = sorted(xs)
    p = (len(xs) - 1) * q
    lo = int(math.floor(p)); hi = int(math.ceil(p))
    return xs[lo] + (xs[hi] - xs[lo]) * (p - lo)

def kst(value):
    return dt.datetime.fromisoformat(value).astimezone(dt.timezone(dt.timedelta(hours=9))).isoformat()

def count_payload(payload, selector):
    n = payload['n']
    pairs = payload.get('pairs', [payload.get('pair')])
    pairs = [tuple(x) for x in pairs]
    observed = {}
    histogram_shots = 0
    shot_values = set()
    for row in payload['data']:
        pair = tuple(row.get('pair', payload.get('pair', [])))
        key = (pair, int(row['z_rest_int']), row['setting'])
        check(key not in observed, f'{selector}: duplicate count key {key}')
        observed[key] = row
        check(pair in pairs, f'{selector}: undeclared pair {pair}')
        check(row['setting'] in SETTINGS, f'{selector}: undeclared setting')
        total = sum(row['counts'].values())
        check(set(row['counts']).issubset({'0','1'}), f'{selector}: unexpected bit keys')
        check(total == row['shots'], f'{selector}: histogram/entry shot mismatch')
        check(all(isinstance(v,int) and v >= 0 for v in row['counts'].values()), f'{selector}: invalid count')
        histogram_shots += total
        shot_values.add(row['shots'])
    expected = {(pair,z,setting) for pair in pairs for z in range(2**(n-2)) for setting in SETTINGS}
    check(set(observed)==expected, f'{selector}: missing or unexpected context-setting combination')
    points = []
    for pair in pairs:
        kappas=[]; amps=[]
        for z in range(2**(n-2)):
            m={s:(observed[pair,z,s]['counts'].get('0',0)-observed[pair,z,s]['counts'].get('1',0))/observed[pair,z,s]['shots'] for s in SETTINGS}
            ua=complex(m['cos_a'],m['sin_a']); ub=complex(m['cos_b'],m['sin_b'])
            kappas.append(cmath.phase(ua*ub.conjugate()))
            amps.append(min(abs(ua),abs(ub)))
        mean=sum(cmath.exp(1j*k) for k in kappas)/len(kappas)
        points.append({'pair':list(pair),'contexts':len(kappas),'V_circ_raw':max(0.0,min(1.0,1.0-abs(mean))),
                       'circular_mean_rad':cmath.phase(mean),'amp_min_mean':statistics.mean(amps),'amp_min_q10':quantile(amps,.1)})
    return {'selector':selector,'n':n,'schema':payload['schema'],'pairs':[list(x) for x in pairs],
            'header_shots_per_circuit':payload.get('shots_per_circuit'),'entry_shots':sorted(shot_values),
            'count_entries':len(payload['data']),'histogram_shots':histogram_shots,
            'context_pair_rows':len(expected)//4,'raw_point_metrics':points,
            'raw_point_metric_scope':'Recomputed on 2026-11-10 directly from retained histograms, no bootstrap, filtering or new QPU acquisition; not a historical published figure point.'}

def metadata_summary(d, path, selector, eta=None, wrapper_run=None):
    return {'run_id':d['run_id'],'metadata_path':path,'metadata_selector':selector,
            'eta3':eta,'wrapper_run':wrapper_run,'mode':d.get('mode','simulation'),
            'n':d['model']['n'],'start_time_recorded':d['start_time'],'end_time_recorded':d['end_time'],
            'start_time_kst':kst(d['start_time']),'end_time_kst':kst(d['end_time']),
            'num_rows_recorded':d['num_rows'],'duration_seconds_recorded':d['duration_seconds'],
            'runtime_code_commit':None,'runtime_dirty_state':None,
            'runtime_identity_note':'No execution source commit or dirty-state manifest is present in the retained run metadata. Import commits are publication snapshots, not established runtime identities.',
            'exit_code':d.get('exit_code'),'errors':d.get('errors'),'warnings':d.get('warnings'),
            'dropped_contexts':d.get('dropped_contexts'),'versions':d.get('versions'),
            'configuration':d['config']}

sim_meta=read_json('data/sim/grid_BFS_Shell_run_meta.json')
sim_stats=read_json('data/sim/grid_BFS_Shell_stats_meta.json')
sim_rows=read_csv('data/sim/grid_BFS_Shell_rows.csv')
sim_summary=read_csv('data/sim/grid_BFS_Shell_trial_summary.csv')
sim_by_en=defaultdict(list)
sim_by_key=defaultdict(list)
for row in sim_rows:
    en=(float(row['eta3']),int(row['n']))
    key=(*en,int(row['i']),int(row['j']),int(row['trial_id']))
    sim_by_en[en].append(row);sim_by_key[key].append(row)

stats_by_id={}
for block in sim_stats:
    for d in block['data']:
        rid=d['input_run_dir'].replace('\\','/').rsplit('/',1)[-1]
        check(rid not in stats_by_id, f'duplicate sim stats run_id {rid}')
        stats_by_id[rid]=dict(d,eta3=block['eta3'],wrapper_run=block['run'])

summary_by_en=defaultdict(list)
summary_errors=defaultdict(float)
summary_seen=set()
for row in sim_summary:
    en=(float(row['eta3']),int(row['n']))
    key=(*en,int(row['i']),int(row['j']),int(row['trial_id']))
    check(key not in summary_seen,f'duplicate sim summary key {key}');summary_seen.add(key)
    rows=sim_by_key[key]; summary_by_en[en].append(row)
    check(len(rows)==int(row['num_contexts']), f'sim summary context mismatch {key}')
    kappas=[float(r['kappa_hat']) for r in rows]
    mean=sum(cmath.exp(1j*k) for k in kappas)/len(kappas)
    amps=[min(float(r['amp_a']),float(r['amp_b'])) for r in rows]
    actual={'kappa_ctx_R_trial':abs(mean),'kappa_ctx_circ_var_trial':max(0.0,min(1.0,1-abs(mean))),
            'kappa_ctx_circ_mean_trial':cmath.phase(mean),'amp_min_mean_ctx_trial':statistics.mean(amps),
            'amp_min_q10_ctx_trial':quantile(amps,.1)}
    for name,value in actual.items():
        delta=abs(value-float(row[name]))
        if name.endswith('mean_trial') and name.startswith('kappa'):
            delta=abs(cmath.phase(cmath.exp(1j*(value-float(row[name])))))
        summary_errors[name]=max(summary_errors[name],delta)
        check(delta<5e-8,f'sim summary numerical mismatch {key}/{name}: {delta}')
check(set(sim_by_key)==summary_seen, 'unrepresented simulator row group')

executions=[]; cards=[]
for bi,block in enumerate(sim_meta):
    eta=float(block['eta3']); group=[]
    for mi,d in enumerate(block['data']):
        n=d['model']['n']; en=(eta,n); rows=sim_by_en[en]; summary=summary_by_en[en]
        scan=d['config']['scan']; pairs=[tuple(x) for x in scan['resolved_pairs']]
        expected={(i,j,z,t) for i,j in pairs for z in range(2**(n-2)) for t in range(d['config']['trials']['count'])}
        observed=[(int(r['i']),int(r['j']),int(r['z_rest_int']),int(r['trial_id'])) for r in rows]
        check(set(observed)==expected and len(observed)==len(expected),f'sim full grid mismatch {en}')
        check(d['num_rows']==len(rows),f'sim meta row count mismatch {en}')
        check({s['run_id'] for s in summary}=={d['run_id']},f'sim run id mismatch {en}')
        check(d['run_id'] in stats_by_id,f'missing stats metadata {d["run_id"]}')
        stats=stats_by_id[d['run_id']]
        check(float(stats['eta3'])==eta and stats['wrapper_run']==block['run'],f'stats wrapper mismatch {en}')
        v=metadata_summary(d,'data/sim/grid_BFS_Shell_run_meta.json',f'$[{bi}].data[{mi}]',eta,block['run'])
        v.update({'execution_family':'simulation','pairs':[list(x) for x in pairs],
                  'trials':d['config']['trials']['count'],'retained_context_rows':len(rows),'retained_pair_trial_summaries':len(summary),
                  'row_join_keys':['eta3','n','i','j','trial_id','z_rest_int'],
                  'rows_have_run_id':False,'run_id_binding':'Matched via the unique retained eta3/n group to trial_summary.run_id and metadata; raw combined rows do not carry run_id.',
                  'stats_meta_created_at':stats['created_at_utc'],
                  'model_runtime_sha256':None,'model_binding_note':'Simulation metadata contains n and effective config, but no model YAML hash or execution source hash.'})
        executions.append(v);group.append(v)
    cards.append({'key':f'sim_eta{eta:g}','kind':'simulation_campaign','eta3':eta,'wrapper_run':block['run'],
                  'execution_ids':[x['run_id'] for x in group],'executions':len(group),
                  'context_rows':sum(x['retained_context_rows'] for x in group),
                  'pair_trial_summaries':sum(x['retained_pair_trial_summaries'] for x in group),
                  'n_specific_trials':sum(x['trials'] for x in group),
                  'sources':['data/sim/grid_BFS_Shell_run_meta.json','data/sim/grid_BFS_Shell_rows.csv','data/sim/grid_BFS_Shell_trial_summary.csv','data/sim/grid_BFS_Shell_stats_meta.json'],
                  'limits':['The wrapper run=2 is an import grouping label; no run=1 evidence is retained here.',
                            'No simulator exit_code/errors fields, environment versions, runtime code SHA or model-file hash are retained. End times and complete row/summary coverage establish the observed exported products.']})

qmeta=read_json('data/qpu/qpu_run_meta.json');qcounts=read_json('data/qpu/qpu_counts.json')
qcount_groups={(float(x['eta3']),x['run']):(i,x) for i,x in enumerate(qcounts)}
job_ids=[]; model_checks=[]; count_checks=[]; raw_points=[]
def qpu_metadata_check(d, eta, path, selector, wrapper_run, scope):
    v=metadata_summary(d,path,selector,eta,wrapper_run)
    n=d['model']['n']; model_path=f'src/qpu/models_ibm_fez_eta{int(round(eta*10)):02d}/diagonal_model_ibm_fez_subgraph_n{n}.yaml'
    m=digest(model_path);snap=digest('src/qpu/ibm_fez_full_20251231_220523.json')
    check(m['sha256']==d['model']['model_yaml_sha256'],f'model runtime hash mismatch {selector}')
    check(snap['sha256']==d['backend_snapshot']['snapshot_sha256'],f'backend snapshot hash mismatch {selector}')
    check(d['exit_code']==0 and not d['errors'] and not d['dropped_contexts'],f'non-success QPU metadata {selector}')
    validations=d['validation'] if isinstance(d['validation'],list) else [d['validation']]
    check(all(x['passed'] for x in validations),f'QPU validation failed {selector}')
    for job in d['jobs']:job_ids.append(job['job_id'])
    model_checks.append({'metadata_path':path,'selector':selector,'model_path':model_path,
                         'recorded_sha256':d['model']['model_yaml_sha256'],'observed_sha256':m['sha256'],
                         'snapshot_sha256':snap['sha256'],'exact_model_bytes_match':True,'exact_backend_snapshot_bytes_match':True})
    v.update({'execution_family':'qpu','metadata_scope':scope,'pairs':d['protocol'].get('pairs',[d['protocol'].get('pair')]),
              'config_shots':d['config']['shots'],'model_path':model_path,'model_runtime_sha256':m['sha256'],
              'backend_snapshot_path':snap['path'],'backend_snapshot_sha256':snap['sha256'],
              'jobs':d['jobs'],'validation':d['validation'],'cache_key':d.get('cache',{}).get('cache_key'),
              'cached_transpilation_reused':d.get('cache',{}).get('reused'),
              'transpiled_circuit_payload_retained':False,'schedule':d.get('schedule'),
              'qpy_limit':'Metadata references local cache and run QPY/manifests. Those exact transpiled artifacts are not in the inspected repository snapshots.'})
    return v

for bi,block in enumerate(qmeta):
    eta=float(block['eta3']);run=block['run']; ci,cblock=qcount_groups[eta,run]
    check(len(block['data'])==1, f'unexpected QPU nested wrapper {eta}/{run}')
    nested=block['data'][0]
    check(float(nested['eta3'])==eta and str(nested['run'])==str(run),f'QPU nested wrapper identity mismatch {eta}/{run}')
    counts_by_n={x['n']:(i,x) for i,x in enumerate(cblock['data'])}
    group=[]; qc=[]
    for mi,d in enumerate(nested['data']):
        n=d['model']['n']; ni,payload=counts_by_n[n]
        selector=f'$[{bi}].data[0].data[{mi}]'
        v=qpu_metadata_check(d,eta,'data/qpu/qpu_run_meta.json',selector,run,'Retained final-R8 metadata; not a complete manifest of every contribution to the accumulated 2048-shot histogram.')
        p=count_payload(payload,f'$[{ci}].data[{ni}]')
        check(p['context_pair_rows']==d['num_rows'],f'QPU row count mismatch {eta}/{run}/{n}')
        check(p['entry_shots']==[2048] and p['header_shots_per_circuit']==256, f'unexpected main QPU shot representation {eta}/{run}/{n}')
        check(d['config']['shots']==256 and all(j['shots']==256 for j in d['jobs']),f'unexpected final-R8 job shots {eta}/{run}/{n}')
        check(d['run_id'].startswith('RR_R8_'),f'non-R8 main metadata {selector}')
        v.update({'counts_path':'data/qpu/qpu_counts.json','counts_selector':p['selector'],
                  'nested_wrapper_run_literal':nested['run'],
                  'counts_summary':{k:val for k,val in p.items() if k!='raw_point_metrics'},
                  'shot_provenance_gap':'Retained histograms are 2048 shots per setting, while headers and final-R8 job/config metadata say 256. The 8x ratio is consistent with accumulation but the preceding subrun records and a complete merge manifest are not retained; do not fabricate them.'})
        executions.append(v);group.append(v);qc.append(p)
        count_checks.append(dict(p,path='data/qpu/qpu_counts.json',eta3=eta,wrapper_run=run))
        raw_points += [dict(x,eta3=eta,wrapper_run=run,n=n) for x in p['raw_point_metrics']]
    day='day1' if run in ({0.0:6,0.1:8,0.2:5}[eta],) else 'day2'
    cards.append({'key':f'qpu_{day}_eta{eta:g}','kind':'qpu_campaign','eta3':eta,'wrapper_run':run,'figure_day_label':day,
                  'retained_execution_ids':[x['run_id'] for x in group],'retained_final_R8_metadata_records':len(group),
                  'context_pair_rows':sum(x['context_pair_rows'] for x in qc),'count_entries':sum(x['count_entries'] for x in qc),
                  'effective_histogram_shots':sum(x['histogram_shots'] for x in qc),'shots_per_retained_histogram':2048,
                  'recorded_final_R8_job_shots':256,'sources':['data/qpu/qpu_run_meta.json','data/qpu/qpu_counts.json'],
                  'limits':['Full accumulated-count execution lineage is not retained: only final-R8 metadata is present.',
                            'A later repository publication commit does not establish runtime code identity.',
                            'Day labels follow explicit README selections; raw timestamps and run labels are retained separately.']})

imeta=read_json('data/qpu/ablation_interleaved_run_meta.json');icount=read_json('data/qpu/ablation_interleaved_counts.json')
icount_map={(x['run'],x['number']):(i,x) for i,x in enumerate(icount)}
ig=[];ip=[]
for bi,block in enumerate(imeta):
    d=block['data'];ci,cblock=icount_map[block['run'],block['number']]
    v=qpu_metadata_check(d,0.0,'data/qpu/ablation_interleaved_run_meta.json',f'$[{bi}].data',block['run'],'One distinct retained 512-shot interleaved schedule segment.')
    p=count_payload(cblock['data'],f'$[{ci}].data')
    check(p['context_pair_rows']==d['num_rows'] and p['entry_shots']==[512],f'interleave count/meta mismatch {bi}')
    v.update({'segment_number':block['number'],'counts_path':'data/qpu/ablation_interleaved_counts.json','counts_selector':p['selector'],'counts_summary':{k:val for k,val in p.items() if k!='raw_point_metrics'}})
    executions.append(v);ig.append(v);ip.append(p);count_checks.append(dict(p,path='data/qpu/ablation_interleaved_counts.json',segment_number=block['number']))
    raw_points += [dict(x,schedule_segment=f'I{block["number"]}',eta3=0.0,n=7) for x in p['raw_point_metrics']]
cards.append({'key':'ablation_interleaved','kind':'schedule_ablation_family','eta3':0.0,'n':7,'execution_ids':[x['run_id'] for x in ig],
              'distinct_execution_segments':4,'context_pair_rows_per_segment':64,'shots_per_segment':512,
              'count_entries':sum(x['count_entries'] for x in ip),'effective_histogram_shots':sum(x['histogram_shots'] for x in ip),
              'sources':['data/qpu/ablation_interleaved_run_meta.json','data/qpu/ablation_interleaved_counts.json'],
              'limits':['I1, I2, I3, I4 are separate acquisitions. I_sum in figure analysis is a derived pooled product, not a fifth interleaved acquisition.']})

bmeta=read_json('data/qpu/ablation_block_run_meta.json');bcount=read_json('data/qpu/ablation_block_counts.json')
v=qpu_metadata_check(bmeta,0.0,'data/qpu/ablation_block_run_meta.json','$',None,'One retained blocked-by-setting schedule attempt with four setting-specific submitted jobs.')
bp=count_payload(bcount,'$')
check(bp['context_pair_rows']==bmeta['num_rows'] and bp['entry_shots']==[2048],'blocked count/meta mismatch')
v.update({'counts_path':'data/qpu/ablation_block_counts.json','counts_selector':'$','counts_summary':{k:val for k,val in bp.items() if k!='raw_point_metrics'}})
executions.append(v);count_checks.append(dict(bp,path='data/qpu/ablation_block_counts.json'))
raw_points += [dict(x,schedule_segment='B',eta3=0.0,n=7) for x in bp['raw_point_metrics']]
cards.append({'key':'ablation_blocked','kind':'schedule_ablation_attempt','eta3':0.0,'n':7,'execution_ids':[v['run_id']],
              'distinct_attempts':1,'setting_specific_jobs':4,'shots_per_setting':2048,
              'context_pair_rows':bp['context_pair_rows'],'count_entries':bp['count_entries'],'effective_histogram_shots':bp['histogram_shots'],
              'sources':['data/qpu/ablation_block_run_meta.json','data/qpu/ablation_block_counts.json'],
              'limits':['The four blocked setting jobs belong to one attempt; they are not four independent repeats.']})

check(len({x['run_id'] for x in executions})==len(executions),'duplicate retained metadata run_id')
check(len(set(job_ids))==len(job_ids),'duplicate retained QPU job id')
all_data_paths=sorted(p for p in EXPECTED_SOURCE_SHA256 if p.startswith('data/'))
source_paths=all_data_paths+sorted({x['model_path'] for x in executions if 'model_path' in x})+[
 'src/qpu/ibm_fez_full_20251231_220523.json','src/qpu/qiskit_runner.py','src/qpu/qiskit_runner_two_pairs.py',
 'src/qpu/qiskit_runner_two_pairs_block.py','src/qpu/qiskit_runner.yaml','src/qpu/qiskit_runner_two_pairs.yaml',
 'src/sim/sim_runner.py','src/sim/stats.py','src/sim/sim_runner.yaml','src/sim/model_provider.py','src/qpu/model_provider.py']
sources=[digest(p) for p in sorted(set(source_paths))]

sim_group_summary=[]
for eta in [0.0,0.1,0.2]:
    for n in range(2,8):
        g=summary_by_en[eta,n]
        for pair in sorted({(int(x['i']),int(x['j'])) for x in g}):
            vals=[float(x['kappa_ctx_circ_var_trial']) for x in g if (int(x['i']),int(x['j']))==pair]
            sim_group_summary.append({'eta3':eta,'n':n,'pair':list(pair),'pair_trial_summaries':len(vals),
                                      'V_circ_mean_over_retained_trials':statistics.mean(vals),
                                      'V_circ_min_over_retained_trials':min(vals),'V_circ_max_over_retained_trials':max(vals)})

result={'schema_version':1,'catalogued_on':CATALOGUED_ON,'scope':'Retained source/read-only reconciliation; no new simulation, QPU job or bootstrap was executed.',
        'repository_snapshots':{'jisung-jung88/kappa-profile':'a49a198e6327f42323e0f43c17ef58d8c535c15c',
                                'jisung-jung88/plaquette-curvature-profiles':'bd4e4f24175d71a360f86bd88fda35c91ae30219'},
        'counts':{'proposed_run_family_cards':len(cards),'retained_metadata_records':len(executions),
                  'simulator_execution_records':18,'main_qpu_final_R8_metadata_records':36,
                  'ablation_execution_records':5,'unique_retained_QPU_job_ids':len(set(job_ids)),
                  'simulation_context_rows':len(sim_rows),'simulation_pair_trial_summary_rows':len(sim_summary),
                  'simulation_n_specific_trials':sum(x['trials'] for x in executions if x['execution_family']=='simulation'),
                  'QPU_count_entries':sum(x['count_entries'] for x in count_checks),
                  'QPU_retained_histogram_shots':sum(x['histogram_shots'] for x in count_checks)},
        'proposed_cards':cards,'executions':executions,'count_checks':count_checks,
        'model_snapshot_hash_checks':model_checks,'source_files':sources,
        'simulation_summary_recalculation':{'groups_checked':len(sim_summary),'tolerance':5e-8,'max_absolute_errors':dict(summary_errors),
           'tolerance_note':'Some small stored circular variances use three-significant-digit scientific notation (e.g. 4.11E-05), so their decimal quantization reaches 5e-8. Raw row angles and other summary columns are also rounded exports.'},
        'simulation_group_metrics':sim_group_summary,
        'reconstruction_tool':{'path':'scripts/reconstruct_run_inventory.py',
          'blob_sha':hashlib.sha1(b'blob '+str(len(Path(__file__).read_bytes())).encode()+b'\0'+Path(__file__).read_bytes()).hexdigest(),
          'sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'commit':None,'commit_note':'Exact tool bytes can be located in local Git history; do not guess a future self commit.'},
        'errors':errors}
metrics_result = {'catalogued_on': CATALOGUED_ON,
    'scope': 'Simple deterministic arithmetic on retained data. Simulator metrics summarize original trial_summary rows; QPU metrics are raw-count points, not historical bootstrap-median figure values.',
    'simulation': sim_group_summary, 'QPU_raw_point_metrics': raw_points}

def emit(value, destination):
    content = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if destination is None:
        sys.stdout.write(content)
        return
    destination = destination.resolve()
    protected = {(SRC / p).resolve() for p in EXPECTED_SOURCE_SHA256}
    protected.add(Path(__file__).resolve())
    if destination in protected:
        raise SystemExit('Refusing to overwrite an original source or the reconstruction tool.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding='utf-8')
    logger.info('Wrote %s', destination)

if args.output and args.metrics_output and args.output.resolve() == args.metrics_output.resolve():
    raise SystemExit('--output and --metrics-output must be different files.')
emit(result, args.output)
if args.metrics_output:
    emit(metrics_result, args.metrics_output)
if errors:
    logger.error('%d historical evidence check(s) failed.', len(errors))
    raise SystemExit(1)
logger.info('Reconciled %d retained metadata records and %d count entries; all checks passed.',
            result['counts']['retained_metadata_records'], result['counts']['QPU_count_entries'])
