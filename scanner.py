import urllib.request
import urllib.parse
import json
import os

# ============================================================
# CONFIGURACION
# ============================================================
API_KEY        = os.environ.get('ODDS_API_KEY', 'bc25c24c196ce27e1080ca5a6cf439d1')
TG_TOKEN       = os.environ.get('TG_TOKEN', '')
TG_CHAT_ID     = os.environ.get('TG_CHAT_ID', '')
MAX_ARB_PCT    = 8.0
CAPITAL        = 100.0

SPORTS = [
    ('soccer_spain_la_liga',                 'La Liga'),
    ('soccer_epl',                           'Premier League'),
    ('soccer_italy_serie_a',                 'Serie A'),
    ('soccer_france_ligue_one',              'Ligue 1'),
    ('soccer_efl_champ',                     'Championship'),
    ('soccer_uefa_champs_league',            'Champions League'),
    ('soccer_uefa_europa_league',            'Europa League'),
    ('soccer_uefa_europa_conference_league', 'Conference League'),
    ('soccer_spain_segunda_division',        'Segunda Division'),
]

# ============================================================
# OBTENER CUOTAS
# ============================================================
def fetch_odds(sport_key, bookmakers):
    bm_str = ','.join(bookmakers)
    url = (
        'https://api.the-odds-api.com/v4/sports/' + sport_key +
        '/odds/?apiKey=' + API_KEY +
        '&regions=eu&markets=h2h,totals&oddsFormat=decimal&bookmakers=' + bm_str
    )
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode('utf-8')
            return json.loads(data)
    except Exception as e:
        print('Error fetching ' + sport_key + ': ' + str(e))
        return []

# ============================================================
# BUSCAR ARBITRAJE
# ============================================================
def find_arbs(games, sport_name, bookmakers, capital):
    opps = []
    for game in games:
        mkts = {}
        for bm in game.get('bookmakers', []):
            if bm['key'] not in bookmakers:
                continue
            for mkt in bm.get('markets', []):
                if mkt['key'] not in mkts:
                    mkts[mkt['key']] = {}
                for oc in mkt.get('outcomes', []):
                    k = oc['name'] + (('_' + str(oc['point'])) if 'point' in oc and oc['point'] is not None else '')
                    if k not in mkts[mkt['key']] or mkts[mkt['key']][k]['odd'] < oc['price']:
                        mkts[mkt['key']][k] = {
                            'odd': oc['price'],
                            'bookmaker': bm['title'],
                            'bm_key': bm['key'],
                            'name': oc['name'],
                            'point': oc.get('point')
                        }

        for mkt_key, ocs in mkts.items():
            keys = list(ocs.keys())
            if len(keys) < 2:
                continue
            pairs = get_pairs(keys)
            for pair in pairs:
                bm_keys = set(ocs[k]['bm_key'] for k in pair)
                if len(bm_keys) < 2:
                    continue
                implied = sum(1.0 / ocs[k]['odd'] for k in pair)
                if implied >= 1.0:
                    continue
                profit = calc_profit(pair, ocs, capital)
                ret_pct = (profit / capital) * 100
                if ret_pct <= 0 or ret_pct > MAX_ARB_PCT:
                    continue
                opps.append({
                    'home': game.get('home_team', ''),
                    'away': game.get('away_team', ''),
                    'commence': game.get('commence_time', ''),
                    'sport': sport_name,
                    'mkt': 'Resultado' if mkt_key == 'h2h' else 'Mas/Menos',
                    'pair': pair,
                    'ocs': ocs,
                    'implied': implied,
                    'profit': profit,
                    'ret_pct': ret_pct,
                    'capital': capital
                })
    return opps

def get_pairs(keys):
    pairs = []
    if len(keys) == 2:
        pairs.append([keys[0], keys[1]])
    elif len(keys) >= 3:
        pairs.append([keys[0], keys[1], keys[2]])
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                pairs.append([keys[i], keys[j]])
    return pairs

def calc_profit(pair, ocs, capital):
    implied = sum(1.0 / ocs[k]['odd'] for k in pair)
    payouts = []
    for k in pair:
        stake = (capital * (1.0 / ocs[k]['odd'])) / implied
        payouts.append(stake * ocs[k]['odd'])
    return min(payouts) - capital

# ============================================================
# ENVIAR MENSAJE TELEGRAM
# ============================================================
def send_telegram(message):
    if not TG_TOKEN or not TG_CHAT_ID:
        print('Sin credenciales de Telegram')
        return
    url = 'https://api.telegram.org/bot' + TG_TOKEN + '/sendMessage'
    data = urllib.parse.urlencode({
        'chat_id': TG_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
        print('Notificacion enviada a Telegram')
    except Exception as e:
        print('Error enviando Telegram: ' + str(e))

def format_opp(opp, idx):
    implied = opp['implied']
    lines = []
    lines.append('')
    lines.append('ARB #' + str(idx) + ' — ' + opp['sport'])
    lines.append(opp['home'] + ' vs ' + opp['away'])
    lines.append('Mercado: ' + opp['mkt'])
    lines.append('Retorno garantizado: +' + str(round(opp['ret_pct'], 2)) + '%')
    lines.append('')
    for k in opp['pair']:
        o = opp['ocs'][k]
        stake = (opp['capital'] * (1.0 / o['odd'])) / implied
        cobro = stake * o['odd']
        lbl = o['name'] + (' ' + str(o['point']) if o.get('point') is not None else '')
        lines.append('  ' + o['bookmaker'] + ': apuesta ' + str(round(stake, 2)) + 'EUR a "' + lbl + '" (x' + str(round(o['odd'], 2)) + ')')
        lines.append('  Si gana cobras: ' + str(round(cobro, 2)) + 'EUR')
    lines.append('')
    lines.append('Ganancia neta: +' + str(round(opp['profit'], 2)) + 'EUR')
    return '\n'.join(lines)

# ============================================================
# MAIN
# ============================================================
def main():
    bookmakers = ['bet365', 'betfair', 'bwin', 'codere', 'sportium', 'williamhill', 'unibet', '888sport', 'pinnacle']
    all_opps = []
    total_games = 0

    print('Escaneando ' + str(len(SPORTS)) + ' competiciones...')

    for sport_key, sport_name in SPORTS:
        games = fetch_odds(sport_key, bookmakers)
        total_games += len(games)
        opps = find_arbs(games, sport_name, bookmakers, CAPITAL)
        all_opps.extend(opps)
        print(sport_name + ': ' + str(len(games)) + ' partidos, ' + str(len(opps)) + ' arbs')

    all_opps.sort(key=lambda x: x['ret_pct'], reverse=True)
    print('Total: ' + str(total_games) + ' partidos, ' + str(len(all_opps)) + ' oportunidades')

    if not all_opps:
        print('Sin arbitraje ahora mismo — no se envia notificacion')
        return

    msg = '<b>ARB SCANNER — ' + str(len(all_opps)) + ' oportunidad(es) encontrada(s)</b>\n'
    msg += 'Capital: ' + str(int(CAPITAL)) + 'EUR\n'

    for i, opp in enumerate(all_opps[:5], 1):
        msg += format_opp(opp, i)
        msg += '\n' + ('—' * 25)

    msg += '\n\nActua rapido — las cuotas cambian en segundos!'
    send_telegram(msg)

if __name__ == '__main__':
    main()
