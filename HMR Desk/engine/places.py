# shortcut: suburb centre points, not geocoded street addresses (keeps addresses off third-party services)
C = {'arundel': (-27.938, 153.363), 'bahrs scrub': (-27.735, 153.168), 'beenleigh': (-27.716, 153.198), 'pimpama': (-27.817, 153.283),
     'helensvale': (-27.912, 153.334), 'coombabah': (-27.912, 153.365), 'hollywell': (-27.902, 153.395), 'runaway bay': (-27.914, 153.398),
     'biggera waters': (-27.932, 153.400), 'paradise point': (-27.886, 153.396), 'labrador': (-27.944, 153.400), 'main beach': (-27.978, 153.427),
     'gilston': (-28.027, 153.302), 'elanora': (-28.137, 153.459), 'tugun': (-28.147, 153.495), 'ilinga': (-28.147, 153.495), 'banora point': (-28.215, 153.535),
     'robina': (-28.078, 153.385), 'southport': (-27.967, 153.405), 'chevron island': (-28.000, 153.425), 'coomera': (-27.860, 153.320), 'yatala': (-27.745, 153.225), 'kirra': (-28.168, 153.521), 'maudsland': (-27.951, 153.263)}

HOME = {'name': 'Arundel', 'll': list(C['arundel'])}

MEET = {'Bupa Banora Point': 'banora point', 'Estia Robina': 'robina',
        'MAC meeting Bupa Banora Point (onsite)': 'banora point',
        'Facility visits Tweed area (Opal Kirra Beach)': 'kirra'}


def coordinates(place):
    import re
    text = (place or '').casefold().strip()
    text = re.sub(r'\b(?:qld|nsw|act|vic|tas|sa|wa|nt|australia)\b|\b\d{4}\b', '', text).strip(' ,')
    for name in sorted(C, key=len, reverse=True):
        if text == name or text.endswith(', ' + name) or text.endswith(' ' + name):
            return list(C[name])
    return None
