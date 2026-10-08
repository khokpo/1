"""Chart.js config builders (charts are rendered client-side from these JSON configs)."""
PAL = ['#0e7c6b', '#b26a00', '#0b6a8a', '#c62f2f', '#6b5b95', '#2e7d32', '#697672']

def bar(labels, sets, title='', stacked=False, ymax=None, horizontal=False):
    ds = [dict(label=n, data=d, backgroundColor=PAL[i % len(PAL)], borderRadius=4) for i, (n, d) in enumerate(sets)]
    sc = {'y': {'beginAtZero': True, 'stacked': stacked, **({'max': ymax} if ymax else {})}, 'x': {'stacked': stacked}}
    return dict(type='bar', data=dict(labels=labels, datasets=ds), options=dict(responsive=True, indexAxis='y' if horizontal else 'x', scales=sc,
                plugins=dict(title=dict(display=bool(title), text=title), legend=dict(display=len(sets) > 1))))

def line(labels, sets, title='', ymax=100):
    ds = [dict(label=n, data=d, borderColor=PAL[i % len(PAL)], backgroundColor=PAL[i % len(PAL)], tension=.25, pointRadius=4) for i, (n, d) in enumerate(sets)]
    return dict(type='line', data=dict(labels=labels, datasets=ds), options=dict(responsive=True, scales={'y': {'min': 0, 'max': ymax}},
                plugins=dict(title=dict(display=bool(title), text=title))))

def doughnut(labels, data, colors=None, title=''):
    return dict(type='doughnut', data=dict(labels=labels, datasets=[dict(data=data, backgroundColor=colors or PAL)]),
                options=dict(responsive=True, plugins=dict(title=dict(display=bool(title), text=title), legend=dict(position='bottom'))))

def hist(values, title='', bins=10, lo=0, hi=100):
    w = (hi - lo) / bins; counts = [0] * bins
    for v in values: counts[min(bins - 1, max(0, int((v - lo) // w)))] += 1
    return bar([f'{int(lo + i * w)}–{int(lo + (i + 1) * w)}' for i in range(bins)], [('Students', counts)], title)
