from pathlib import Path
import csv, re
base = Path('/Users/a1234/Carnot_Battery_for_DC/pure_deap_nsga/results')
files = sorted(base.glob('pareto_*.csv'))
rows = []
name_map = {'round_trip_efficiency':'eta_p2p','eta_rt':'eta_p2p','eta':'eta_p2p','e_th':'energy_density_thermal','thermal_energy_density':'energy_density_thermal','eta_ex':'exergy_efficiency','ex_eff':'exergy_efficiency'}
for fp in files:
    m = re.match(r'pareto_(DC-[A-F])_(.+)_(R[^_]+)_(R[^_]+)$', fp.stem)
    if not m:
        continue
    wp, rest, hp, he = m.group(1), m.group(2), m.group(3), m.group(4)
    parts = rest.split('_')
    config = '_'.join(parts[:2]) if len(parts) >= 2 else rest
    try:
        with fp.open('r', newline='') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                continue
            canonical = {c: name_map.get(c.lower(), c) for c in reader.fieldnames}
            for rec in reader:
                norm = {canonical[k]: v for k, v in rec.items()}
                try:
                    eta = float(norm.get('eta_p2p','nan'))
                    eth = float(norm.get('energy_density_thermal','nan'))
                    ex = float(norm.get('exergy_efficiency','nan'))
                except ValueError:
                    continue
                if not (eta == eta and eth == eth and ex == ex):
                    continue
                row = {'wp': wp, 'config': config, 'fluid_hp': hp, 'fluid_he': he, 'file': fp.name, 'eta_p2p': eta, 'energy_density_thermal': eth, 'exergy_efficiency': ex}
                for c in ['T_st_ht','dT_st_sp','T_st_lt','cop_hp','eta_he','energy_density_electric','storage_volume']:
                    val = norm.get(c, '')
                    try:
                        row[c] = float(val) if val not in ['', None] else ''
                    except ValueError:
                        row[c] = ''
                rows.append(row)
    except Exception:
        continue

def nondom(records):
    vals = [(r['eta_p2p'], r['energy_density_thermal'], r['exergy_efficiency']) for r in records]
    keep = []
    for i, v in enumerate(vals):
        dominated = False
        for j, u in enumerate(vals):
            if i == j:
                continue
            if all(u[k] >= v[k] for k in range(3)) and any(u[k] > v[k] for k in range(3)):
                dominated = True
                break
        if not dominated:
            keep.append(records[i])
    return keep

def sample(records, limit):
    records = sorted(records, key=lambda r: (r['eta_p2p'], r['energy_density_thermal'], r['exergy_efficiency']))
    if len(records) <= limit:
        return records
    idx = sorted(set(round(i * (len(records) - 1) / (limit - 1)) for i in range(limit)))
    return [records[i] for i in idx]
front = []
for wp in sorted({r['wp'] for r in rows}):
    front.extend(sample(nondom([r for r in rows if r['wp'] == wp]), 180))
cfg = []
for key in sorted({(r['wp'], r['config']) for r in rows}):
    cfg.extend(sample(nondom([r for r in rows if (r['wp'], r['config']) == key]), 60))
summary = []
for key in sorted({(r['wp'], r['config']) for r in rows}):
    g = [r for r in rows if (r['wp'], r['config']) == key]
    summary.append({'wp': key[0], 'config': key[1], 'n': len(g), 'eta_max': max(r['eta_p2p'] for r in g), 'e_max': max(r['energy_density_thermal'] for r in g), 'ex_max': max(r['exergy_efficiency'] for r in g)})
out = Path('/Users/a1234/Carnot_Battery_for_DC/paper_outputs')
out.mkdir(exist_ok=True)
fields = ['wp','config','fluid_hp','fluid_he','file','eta_p2p','energy_density_thermal','exergy_efficiency','T_st_ht','dT_st_sp','T_st_lt','cop_hp','eta_he','energy_density_electric','storage_volume']
for fn, data, fs in [('pareto_front_global_reduced.csv', front, fields), ('pareto_front_by_config_reduced.csv', cfg, fields), ('pareto_source_summary.csv', summary, ['wp','config','n','eta_max','e_max','ex_max'])]:
    with (out / fn).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fs)
        writer.writeheader()
        writer.writerows(data)
print(f'all_rows={len(rows)} global_front_rows={len(front)} config_front_rows={len(cfg)} files={len(files)}')
print(out)
