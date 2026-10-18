import json, sys
base = sys.argv[1]
s = json.load(open(base + '/evaluation_summaries.json'))
new = ['1-LV-rural2--2-sw','1-LV-rural3--2-sw','1-LV-semiurb4--2-sw','1-LV-semiurb5--2-sw','1-LV-urban6--2-sw']
truths = ['nominal','tap_raise_lv','tap_lower_lv','pv_cosphi_p','pv_fixed_095','storage_greedy','storage_profile','mv_high','joint_realistic','joint_loading']
def T(n, cell, p): return s[n]['cells'][cell]['totals'][p]
# 1 sums nominal F1
for p in ['static_dev','replay_aci','oracle','ensemble','point_margin','static_aci','scenario_aci']:
    print(p, 'sum MWh', round(sum(T(n,'forecast/nominal',p)['curtailed_mwh'] for n in new),2), 'steps', sum(T(n,'forecast/nominal',p)['avoidable_violation_steps'] for n in new))
# 2 meets beta counts F1
for p in ['static_dev','static_beta','scenario_robust','replay_robust','ensemble','point_margin','static_aci','scenario_aci','replay_aci']:
    for key in ['meets_beta']:
        c = sum(T(n,'forecast/'+t,p)['meets_beta'] for n in new for t in truths)
    c05 = sum(T(n,'forecast/'+t,p)['meets_exploratory_beta']['0.05'] for n in new for t in truths)
    c2 = sum(T(n,'forecast/'+t,p)['meets_exploratory_beta']['0.2'] for n in new for t in truths)
    print(p, c, c05, c2)
# 3 nominal wins vs static_aci and static_dev
for n in ['1-LV-rural2--2-sw','1-LV-semiurb5--2-sw','1-LV-urban6--2-sw']:
    r = T(n,'forecast/nominal','replay_aci')['curtailed_mwh']
    for q in ['static_aci','static_dev']:
        o = T(n,'forecast/nominal',q)['curtailed_mwh']
        print(n, q, round(o-r,3), 'MWh', round(100*(o-r)/o,1), '%')
# 4 urban6 scenario-replay curtailment ci
pp = s['1-LV-urban6--2-sw']['cells']['forecast/nominal']['paired_per_day']['scenario_aci_minus_replay_aci']['curtailed_mwh']
print('urban6 scen-replay curt', pp)
# 5 static_dev tap_raise / mv_high sums, stress share
tot = 0; stress = 0
for n in new:
    for t in truths[1:]:
        v = T(n,'forecast/'+t,'static_dev')['avoidable_violation_steps']
        tot += v
        if t in ('tap_raise_lv','mv_high','joint_realistic') and n in ('1-LV-rural2--2-sw','1-LV-rural3--2-sw','1-LV-urban6--2-sw'): stress += v
print('static_dev variant failures total', tot, 'stress', stress, round(stress/tot,3))
for t in ['tap_raise_lv','mv_high']:
    print(t, sum(T(n,'forecast/'+t,'static_dev')['avoidable_violation_steps'] for n in new))
# 6 entry states under stress truths
for t in ['tap_raise_lv','mv_high','joint_realistic']:
    for n in ['1-LV-rural2--2-sw','1-LV-rural3--2-sw','1-LV-urban6--2-sw']:
        tod = s[n]['cells']['forecast/'+t]['tuned_on_development']['online_state_end_of_development']
        print(t, n[5:], 'static_aci', round(tod['static_aci_level_index'],2), 'replay_aci', round(tod['replay_aci'],3))
# 7 physical safety nominal F1 new networks
for p in ['static_dev','static_aci','scenario_aci','replay_aci','ensemble']:
    d = sum(T(n,'forecast/nominal',p)['days_with_violation'] for n in new)
    w = max(T(n,'forecast/nominal',p)['worst_day_violation_steps'] for n in new)
    lr = max(T(n,'forecast/nominal',p)['longest_violation_run'] for n in new)
    l1 = sum(T(n,'forecast/nominal',p)['long_runs'] for n in new)
    sv = sum(T(n,'forecast/nominal',p)['severe_steps'] for n in new)
    print(p, d, w, lr, l1, sv)
# 8 mismatch both-meet cells replay vs static_aci
import statistics
rel=[]; below=0; inc=0; above=0
for n in new:
    for t in truths[1:]:
        a = T(n,'forecast/'+t,'replay_aci'); b = T(n,'forecast/'+t,'static_aci')
        if a['meets_beta'] and b['meets_beta']:
            rel.append((a['curtailed_mwh']-b['curtailed_mwh'])/b['curtailed_mwh'])
            ci = s[n]['cells']['forecast/'+t]['paired_per_day']['replay_aci_minus_static_aci']['curtailed_mwh']
            if ci['ci_high'] < 0: below += 1
            elif ci['ci_low'] > 0: above += 1
            else: inc += 1
print('both meet', len(rel), 'median', round(statistics.median(rel),3), 'min', round(min(rel),3), 'max', round(max(rel),3), below, inc, above)
