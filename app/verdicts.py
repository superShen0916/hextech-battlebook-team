"""Short, data-backed praise lines for each analysis page.

Numbers are rebuilt from the current summary every time — nothing about a
player's record is baked into a string, so a refreshed snapshot can never show
stale figures. Only the voice (opening lead / punch line) is curated, and the
pro-player association keeps a hand-confirmed seed while the evidence under it
is recomputed from the champion pool and the numbers.
"""
from __future__ import annotations

from champion_names import CHAMPION_CN

Role = str

CHAMPION_ROLES: dict[str, Role] = {
    'Ryze': 'mage', 'Malzahar': 'mage', 'Syndra': 'mage', 'Yone': 'fighter', 'MissFortune': 'marksman',
    'Graves': 'marksman', 'Kayn': 'assassin', 'Tristana': 'marksman', 'Lucian': 'marksman', 'Jax': 'fighter',
    'Yasuo': 'fighter', 'Caitlyn': 'marksman', 'Darius': 'fighter', 'Brand': 'mage', 'TahmKench': 'tank',
    'Lillia': 'mage', 'Morgana': 'mage', 'Tryndamere': 'fighter', 'Aatrox': 'fighter', 'Mordekaiser': 'fighter',
    'Ekko': 'assassin', 'Twitch': 'marksman', 'Jayce': 'fighter', 'Galio': 'tank', 'Corki': 'marksman',
    'Swain': 'mage', 'Vayne': 'marksman', 'JarvanIV': 'tank', 'DrMundo': 'tank', 'XinZhao': 'fighter',
    'TwistedFate': 'mage', 'MasterYi': 'assassin', 'AurelionSol': 'mage', 'Hecarim': 'fighter', 'Maokai': 'tank',
    'Nocturne': 'assassin', 'Lux': 'mage', 'Karthus': 'mage', 'Ezreal': 'marksman', 'Kassadin': 'assassin',
    'Varus': 'marksman', 'Thresh': 'support', 'Malphite': 'tank', 'Diana': 'assassin', 'Teemo': 'marksman',
    'Jhin': 'marksman', 'Trundle': 'fighter', 'Nasus': 'fighter', 'Sett': 'fighter', 'Sion': 'tank',
    'Garen': 'fighter', 'Quinn': 'marksman', 'Smolder': 'marksman', 'Samira': 'marksman', 'Xayah': 'marksman',
    'Kayle': 'fighter', 'Heimerdinger': 'mage', 'Zed': 'assassin', 'Ziggs': 'mage', 'Volibear': 'fighter',
    'Gangplank': 'fighter', 'MonkeyKing': 'fighter', 'Talon': 'assassin', 'Kindred': 'marksman', 'Kaisa': 'marksman',
    'Fizz': 'assassin', 'Ashe': 'marksman', 'Mel': 'mage', 'Blitzcrank': 'tank', 'Xerath': 'mage',
    'Sylas': 'assassin', 'Sejuani': 'tank', 'Udyr': 'fighter', 'Ornn': 'tank', 'Shaco': 'assassin',
    'Shen': 'tank', 'Senna': 'marksman', 'Nidalee': 'assassin', 'Zyra': 'mage', 'Chogath': 'tank',
    'Briar': 'fighter', 'Pyke': 'assassin', 'Zeri': 'marksman', 'Veigar': 'mage', 'Alistar': 'tank',
    'Zilean': 'support', 'Katarina': 'assassin', 'Draven': 'marksman', 'Singed': 'tank', 'Ahri': 'mage',
    'Qiyana': 'assassin', 'Skarner': 'fighter', 'Seraphine': 'support', 'Zoe': 'mage', 'Leona': 'support',
    'Velkoz': 'mage', 'Gnar': 'fighter', 'Hwei': 'mage', 'Urgot': 'fighter', 'Jinx': 'marksman',
    'Ambessa': 'fighter', 'Kled': 'fighter', 'Rumble': 'fighter', 'LeeSin': 'assassin', 'FiddleSticks': 'mage',
    'Olaf': 'fighter', 'Amumu': 'tank', 'Azir': 'mage', 'Illaoi': 'fighter', 'Aurora': 'mage',
    'Poppy': 'tank', 'Sivir': 'marksman', 'Akshan': 'marksman', 'Renekton': 'fighter', 'Gragas': 'tank',
    'Akali': 'assassin', 'Taliyah': 'mage', 'Viego': 'assassin', 'Zac': 'tank', 'Vi': 'fighter',
    'Orianna': 'mage', 'Gwen': 'fighter', 'Riven': 'fighter', 'Kalista': 'marksman', 'KogMaw': 'marksman',
    'Lulu': 'support', 'Karma': 'support', 'Pantheon': 'fighter', 'Aphelios': 'marksman', 'Viktor': 'mage',
    'Leblanc': 'assassin', 'Nautilus': 'tank', 'Khazix': 'assassin', 'Fiora': 'fighter', 'Neeko': 'mage',
    'Vladimir': 'mage', 'Kennen': 'mage', 'Cassiopeia': 'mage', 'Vex': 'mage', 'Rengar': 'assassin',
    'Rell': 'tank', 'Belveth': 'fighter', 'Braum': 'support', 'RekSai': 'fighter', 'Nami': 'support',
    'KSante': 'tank', 'Shyvana': 'fighter', 'Nilah': 'fighter', 'Annie': 'mage', 'Yorick': 'fighter',
    'Lissandra': 'mage', 'Rammus': 'tank', 'Anivia': 'mage', 'Milio': 'support', 'Janna': 'support',
    'Irelia': 'fighter', 'Yuumi': 'support', 'Sona': 'support', 'Soraka': 'support', 'Ivern': 'support',
    'Nunu': 'tank', 'Elise': 'assassin', 'Renata': 'support', 'Camille': 'fighter', 'Warwick': 'fighter',
    'Rakan': 'support', 'Bard': 'support', 'Taric': 'support',
}

ROLE_LABEL = {'marksman': '射手', 'mage': '法师', 'assassin': '刺客',
              'fighter': '战士', 'tank': '坦克', 'support': '辅助'}

# Curated voice only: an opening lead and a punch line, both free of numbers.
LEADS = {
    '间客丿': '队里最能熬的那一个。',
    'gopher': '最高的山。',
    '好人还遇好人救': '全队的血包兼沙包，两班倒。',
    '碰不到你的灵魂': '两头都沾的全能怪。',
    'LliMaozi': '真神，无需讨论。',
    '十一月的萧邦': '胜率妖怪，走哪赢哪。',
    '柿子蒸螃蟹': '输出位上的硬手。',
    '我要写cpp': '全队最专业的救火队。',
    '雨下喝酒': '人形城墙，移动的禁区。',
    '小无敌520': '效率高得离谱。',
    '淹死的鱼oO丶': '队里最会出现在该出现的地方的人。',
    '上路的老爹': '分数先把人镇住。',
    '破碎浮云帝': '打法师的手都很稳。',
    '快给我看看': '能奶、能抗、还能打一点。',
    '我和我的三个儿': '队里的乐观主义者。',
    'LookOutTheBush': '数据表里最离谱的一行。',
    'VivaLaVida01': '队里唯一把救人当主业的人。',
}

PUNCH = {
    '间客丿': '别人靠天赋，他靠出勤。',
    'gopher': '别人在打游戏，他在写队史。',
    '好人还遇好人救': '戏里没有他的名字，散场时每个人都欠他一声谢。',
    '碰不到你的灵魂': '阵容里最容易散架的那块，通常由他顶住。',
    'LliMaozi': '队友负责配合，他负责终结。',
    '十一月的萧邦': '别人练操作，他练的是玄学。',
    '柿子蒸螃蟹': '他不一定赢，但他一定打。',
    '我要写cpp': '他的 ACE 不是奖状，是队友欠的账。',
    '雨下喝酒': '他往前站一步，后排才敢做梦。',
    '小无敌520': '出场费按场算，存在感按局算。',
    '淹死的鱼oO丶': '有些人的价值，只有被他控住的人才懂。',
    '上路的老爹': '有的人靠数据说话，他的分数已经替他说完了。',
    '破碎浮云帝': '手长不是本事，手稳才是。',
    '快给我看看': '队里缺什么他就补什么，还补得不难看。',
    '我和我的三个儿': '赢得不多不少，刚好够让人想再来一局。',
    'LookOutTheBush': '别人算血条，他算的是还能冲几次。',
    'VivaLaVida01': '有人负责拿人头，他负责让人头有机会被拿。',
}

# Hand-confirmed pro association wins over the rule, but the evidence is always recomputed.
CURATED_PRO = {
    '间客丿': {'pro': 'Faker', 'tag': '全能常青'},
    'gopher': {'pro': 'Doinb', 'tag': '功能型核心'},
    '好人还遇好人救': {'pro': 'Meiko', 'tag': '保护型辅助'},
    '碰不到你的灵魂': {'pro': 'Rookie', 'tag': '全能补位'},
    'LliMaozi': {'pro': 'Uzi', 'tag': '极致输出'},
    '十一月的萧邦': {'pro': 'Chovy', 'tag': '稳定输出'},
    '柿子蒸螃蟹': {'pro': 'TheShy', 'tag': '上单花活'},
    '我要写cpp': {'pro': 'Ming', 'tag': '开团辅助'},
    '雨下喝酒': {'pro': '369', 'tag': '前排模板'},
    '小无敌520': {'pro': 'Knight', 'tag': '刺客本能'},
    '淹死的鱼oO丶': {'pro': 'Xiaohu', 'tag': '万金油'},
    '上路的老爹': {'pro': 'Zeus', 'tag': '全能上单'},
    '破碎浮云帝': {'pro': 'ShowMaker', 'tag': '远程法师'},
    '快给我看看': {'pro': 'Keria', 'tag': '多面手'},
    '我和我的三个儿': {'pro': 'Rookie', 'tag': '全能补位'},
    'LookOutTheBush': {'pro': 'Kanavi', 'tag': '野区怪物'},
    'VivaLaVida01': {'pro': 'Keria', 'tag': '多面手'},
}


# 每位选手的一句话风格，用来把数据画像和人选对上。
PRO_STYLE = {
    'Uzi': '以 AD 核心的极致输出著称',
    'Ruler': '沉得住气、把伤害稳定交出来的 AD',
    'JackeyLove': '自己找机会的激进派输出',
    'Deft': '愿意为队伍把脏活接下的老将 AD',
    'Chovy': '每一刀都算过的稳健派',
    'ShowMaker': '站在两个屏幕外要人命的远程法师',
    'Rookie': '不挑英雄、哪缺补哪的全能中单',
    'Doinb': '输出和承伤一手抓的功能型核心',
    'Knight': '切后排不需要理由的刺客手感',
    'Tarzan': '抓机会下手极快的野区猎手',
    'TheShy': '把射手和花活带上路的那个性子',
    'Zeus': '上路的稳定与全能',
    'Bin': '敢一打多的上路对拼',
    '369': '顶在最前面还带输出的前排',
    'Meiko': '把保护和开团都揽下来的辅助',
    'Ming': '钩子一出手就是开团信号的辅助',
    'Keria': '什么位置都能上的多面手',
    'Xiaohu': '哪都能打、局面从不缺他',
    'Kanavi': '能吃不亏、打完还能站着的野区打法',
    'Faker': '什么位置都拿得起、常年一线的全能',
}


def _f(value):
    return value if isinstance(value, (int, float)) else 0


def role_profile(champions=None):
    """Champion pool -> {'total', 'stats', 'top', 'mixed'}; unknown champs stay out of the denominator."""
    counts: dict[str, int] = {}
    total = 0
    for row in champions or []:
        if not isinstance(row, dict):
            continue
        role = CHAMPION_ROLES.get(row.get('champion_name') or '')
        if not role:
            continue
        games = _f(row.get('games'))
        counts[role] = counts.get(role, 0) + int(games)
        total += int(games)
    stats = [{'role': r, 'games': g, 'share': (g / total) if total else 0}
             for r, g in sorted(counts.items(), key=lambda kv: -kv[1])]
    top = stats[0] if stats else None
    return {'total': total, 'stats': stats, 'top': top, 'mixed': (not top) or top['share'] < 0.35}


def pick_pro(profile, summary):
    role = (profile.get('top') or {}).get('role')
    mixed = profile.get('mixed', True)
    share = _f(summary.get('damage_share'))
    dpm = _f(summary.get('dpm'))
    kda = _f(summary.get('kda'))
    taken = _f(summary.get('taken'))
    heal = _f(summary.get('heal'))
    join = _f(summary.get('kill_participation'))
    if not mixed:
        if role == 'marksman':
            if share >= 0.23 or dpm >= 2800:
                return {'pro': 'Uzi', 'tag': '极致输出'}
            if kda >= 3.8:
                return {'pro': 'Ruler', 'tag': '沉着 AD'}
            if join >= 0.70:
                return {'pro': 'JackeyLove', 'tag': '激进输出'}
            return {'pro': 'Deft', 'tag': '团队老将'}
        if role == 'mage':
            if taken >= 55000:
                return {'pro': 'Doinb', 'tag': '功能型核心'}
            if kda >= 3.8:
                return {'pro': 'Chovy', 'tag': '稳定输出'}
            if share >= 0.21 or dpm >= 2600:
                return {'pro': 'ShowMaker', 'tag': '远程法师'}
            return {'pro': 'Rookie', 'tag': '全能补位'}
        if role == 'assassin':
            if kda >= 3.5:
                return {'pro': 'Knight', 'tag': '刺客本能'}
            if join >= 0.68:
                return {'pro': 'Tarzan', 'tag': '野区猎手'}
            return {'pro': 'Knight', 'tag': '刺客本能'}
        if role == 'fighter':
            if taken >= 55000:
                return {'pro': '369', 'tag': '前排模板'}
            if dpm >= 2500:
                return {'pro': 'TheShy', 'tag': '上单花活'}
            if kda >= 3.6:
                return {'pro': 'Zeus', 'tag': '全能上单'}
            return {'pro': 'Bin', 'tag': '上路硬拼'}
        if role == 'tank':
            if heal >= 500:
                return {'pro': 'Keria', 'tag': '多面手'}
            return {'pro': '369', 'tag': '前排模板'}
        if role == 'support':
            if heal >= 600:
                return {'pro': 'Meiko', 'tag': '保护型辅助'}
            if join >= 0.68:
                return {'pro': 'Ming', 'tag': '开团辅助'}
            return {'pro': 'Keria', 'tag': '多面手'}
    if heal >= 600:
        return {'pro': 'Keria', 'tag': '多面手'}
    if taken >= 55000:
        return {'pro': '369', 'tag': '前排模板'}
    if share >= 0.23 or dpm >= 2800:
        return {'pro': 'Uzi', 'tag': '极致输出'}
    if kda >= 3.8:
        return {'pro': 'Chovy', 'tag': '稳定输出'}
    if join >= 0.68:
        return {'pro': 'Ming', 'tag': '开团辅助'}
    return {'pro': 'Faker', 'tag': '全能常青'}


def _pro_text(pro, tag, summary, profile, champions=None):
    facts = []
    if summary.get('damage_share') is not None:
        facts.append(f"团队伤害占比 {_f(summary.get('damage_share')) * 100:.1f}%")
    if summary.get('dpm') is not None:
        facts.append(f"每分钟 {_f(summary.get('dpm')):.0f} 伤害")
    if summary.get('kda') is not None:
        facts.append(f"KDA {_f(summary.get('kda')):.2f}")
    if _f(summary.get('taken')) >= 40000:
        facts.append(f"场均承伤 {_f(summary.get('taken')) / 10000:.1f} 万")
    if _f(summary.get('heal')) >= 300:
        facts.append(f"场均治疗 {_f(summary.get('heal')):.0f}")
    if summary.get('kill_participation') is not None:
        facts.append(f"参团率 {_f(summary.get('kill_participation')) * 100:.1f}%")
    evidence = '、'.join(facts[:3])
    pool = ''
    names = [(c or {}).get('champion_name') for c in (champions or [])[:3]]
    names = [CHAMPION_CN.get(x, x) for x in names if x]
    if names:
        pool = '常用 ' + '、'.join(names) + '；'
    top = profile.get('top')
    if not profile.get('mixed') and top:
        role_part = f"英雄池里{ROLE_LABEL.get(top['role'], top['role'])}占 {top['share'] * 100:.0f}%"
    else:
        role_part = '英雄池铺得开、没有单一主定位'
    style = PRO_STYLE.get(pro, '风格鲜明的一线选手')
    return f"{pool}{role_part}，{evidence}——和 {pro} 那种「{style}」的路子对得上。"


def _body(summary, awards, rating, profile):
    """Every number here comes from the current view; nothing is hard-coded."""
    games = _f(summary.get('games'))
    parts = [f"{games:.0f} 场有效样本"]
    if summary.get('win_rate') is not None:
        parts.append(f"胜率 {_f(summary.get('win_rate')) * 100:.1f}%")
    lines = ['、'.join(parts) + '。']
    facts = []
    if summary.get('dpm') is not None:
        facts.append(f"每分钟 {_f(summary.get('dpm')):.0f} 伤害")
    if summary.get('damage_share') is not None:
        facts.append(f"团队占比 {_f(summary.get('damage_share')) * 100:.1f}%")
    if _f(summary.get('taken')) >= 40000:
        facts.append(f"场均承伤 {_f(summary.get('taken')) / 10000:.1f} 万")
    if _f(summary.get('heal')) >= 300:
        facts.append(f"场均治疗 {_f(summary.get('heal')):.0f}")
    if summary.get('kda') is not None:
        facts.append(f"KDA {_f(summary.get('kda')):.2f}")
    if facts:
        lines.append('、'.join(facts) + '。')
    if isinstance(awards, dict):
        bits = []
        if awards.get('mvp'):
            bits.append(f"{_f(awards.get('mvp')):.0f} 次自评 MVP")
        if awards.get('ace'):
            bits.append(f"{_f(awards.get('ace')):.0f} 次败方 ACE")
        if bits:
            lines.append('、'.join(bits) + '，亮点留在每一张战报里。')
    if isinstance(rating, dict) and rating.get('status') == 'estimated' and rating.get('score') is not None:
        score = rating.get('score')
        top = rating.get('top_percent')
        lines.append(f"海斗分 {score:.0f}" + (f"、本区前 {top:.1f}%" if isinstance(top, (int, float)) else "") + "。")
    return ''.join(lines)


def verdict_for(name, summary, awards=None, rating=None, champions=None):
    """Return {'text', 'punch', 'pro'} for one analysis subject, or None."""
    if not isinstance(summary, dict) or _f(summary.get('games')) < 1:
        return None
    name = name if isinstance(name, str) else ''
    profile = role_profile(champions)
    pro = CURATED_PRO.get(name) or pick_pro(profile, summary)
    lead = LEADS.get(name) or '每场都交出自己的那份贡献。'
    punch = PUNCH.get(name) or '精彩不只在最后一次击杀里。'
    return {
        'text': lead + _body(summary, awards, rating, profile),
        'punch': punch,
        'pro': {'pro': pro['pro'], 'tag': pro['tag'],
                'text': _pro_text(pro['pro'], pro['tag'], summary, profile, champions)},
    }
