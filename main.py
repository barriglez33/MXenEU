import hashlib, html, json, re, time, unicodedata
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote_plus, urlsplit, urlunsplit, parse_qsl, urlencode
import feedparser, requests, trafilatura
from googlenewsdecoder import gnewsdecoder
from deep_translator import GoogleTranslator

ROOT=Path(__file__).resolve().parent; CONFIG_FILE=ROOT/'config.json'; DATA=ROOT/'data'; DOCS=ROOT/'docs'; PF=DOCS/'players'; DB=DATA/'articles.json'

def cfg(): return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
def load():
    try: return json.loads(DB.read_text(encoding='utf-8'))
    except: return []
def save(x): DB.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def deaccent(s): return ''.join(c for c in unicodedata.normalize('NFKD',str(s)) if not unicodedata.combining(c))
def norm(s): return re.sub(r'\s+',' ',deaccent(s).lower()).strip()
def aliases(name):
    a={name.strip(),deaccent(name).strip()}
    if norm(name)=='alex padilla': a.add('Álex Padilla')
    return sorted(x for x in a if x)
def slug(s): return re.sub(r'[^a-z0-9]+','-',norm(s)).strip('-')
def query(name):
    q=[f'"{x}"' for x in aliases(name)]; return q[0] if len(q)==1 else '('+' OR '.join(q)+')'
def clean(u):
    try:
        p=urlsplit(u); q=[]
        for k,v in parse_qsl(p.query,keep_blank_values=True):
            if k.lower().startswith('utm_') or k.lower() in {'fbclid','gclid','mc_cid','mc_eid'}: continue
            q.append((k,v))
        return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),''))
    except: return u
def domain(u):
    try:
        h=urlsplit(u).netloc.lower(); return h[4:] if h.startswith('www.') else h
    except: return ''
def aid(u): return hashlib.sha256(u.encode()).hexdigest()[:20]
def cd(s): return '<![CDATA['+str(s).replace(']]>',']]]]><![CDATA[>')+']]>'
def dt(v):
    if not v: return datetime.now(timezone.utc)
    for f in ('%Y%m%dT%H%M%SZ','%Y%m%d%H%M%S','%Y-%m-%dT%H:%M:%SZ','%Y-%m-%d %H:%M:%S'):
        try: return datetime.strptime(str(v),f).replace(tzinfo=timezone.utc)
        except: pass
    return datetime.now(timezone.utc)
def feed_dt(e):
    for a in ('published_parsed','updated_parsed'):
        p=getattr(e,a,None)
        if p: return datetime(p.tm_year,p.tm_mon,p.tm_mday,p.tm_hour,p.tm_min,p.tm_sec,tzinfo=timezone.utc)
    return datetime.now(timezone.utc)

def gdelt(player,c):
    if not c['settings'].get('use_gdelt',True): return []
    params={'query':query(player['name']),'mode':'artlist','maxrecords':c['settings']['gdelt_results_per_player'],'timespan':f"{c['settings']['max_age_hours']}h",'sort':'datedesc','format':'json'}
    try:
        r=requests.get('https://api.gdeltproject.org/api/v2/doc/doc',params=params,timeout=30,headers={'User-Agent':'MexicanosEnEuropa/1.0'}); r.raise_for_status(); data=r.json()
    except Exception as e: print('  GDELT error:',e); return []
    out=[]
    for x in data.get('articles',[]):
        u=clean(x.get('url',''))
        if u: out.append({'url':u,'title':x.get('title','') or '','source':x.get('domain','') or domain(u),'published':dt(x.get('seendate')),'language':x.get('language','') or '','country':x.get('sourcecountry','') or '','via':'GDELT','player':player})
    return out

def gurl(q,e): return 'https://news.google.com/rss/search?'+f"q={quote_plus(q)}&hl={quote_plus(e['hl'])}&gl={quote_plus(e['gl'])}&ceid={quote_plus(e['ceid'])}"
def decode(u):
    if 'news.google.com' not in u: return clean(u)
    try:
        z=gnewsdecoder(u,interval=1)
        if isinstance(z,dict) and z.get('status') and z.get('decoded_url'): return clean(z['decoded_url'])
    except: pass
    return None

def google(player,c):
    if not c['settings'].get('use_google_news',True): return []
    out=[]; q=query(player['name']); lim=c['settings']['google_results_per_edition']
    for e in c['google_news_editions']:
        f=feedparser.parse(gurl(q,e))
        for x in list(getattr(f,'entries',[]))[:lim]:
            u=decode(getattr(x,'link',''))
            if not u: continue
            src=''
            try:
                if getattr(x,'source',None): src=x.source.get('title','') or ''
            except: pass
            out.append({'url':u,'title':getattr(x,'title','') or '','source':src or domain(u),'published':feed_dt(x),'language':'','country':e['label'],'via':'Google News','player':player})
    return out

def extract(u):
    try:
        d=trafilatura.fetch_url(u)
        if not d: return None
        z=trafilatura.extract(d,url=u,output_format='json',with_metadata=True,include_comments=False,include_tables=True,favor_precision=True)
        if not z: return None
        j=json.loads(z); b=(j.get('text') or '').strip()
        if not b: return None
        return {'title':(j.get('title') or '').strip(),'author':(j.get('author') or '').strip(),'body':b}
    except Exception as e: print('    Extract error:',e); return None

def mentions(text,name):
    n=norm(text); return any(norm(a) in n for a in aliases(name))
def detected(text,ps): return [{'name':p['name'],'club':p['club'],'group':p['group']} for p in ps if mentions(text,p['name'])]
def merge(a,p,cand):
    names={x.get('name') for x in a.setdefault('tracked_players',[])}
    if p['name'] not in names: a['tracked_players'].append({'name':p['name'],'club':p['club'],'group':p['group']})
    if cand['via'] not in a.setdefault('discovery_sources',[]): a['discovery_sources'].append(cand['via'])
    if cand.get('language') and cand['language'] not in a.setdefault('source_languages',[]): a['source_languages'].append(cand['language'])

def rss(items,title,desc,site,maxn):
    rows=[]
    for a in sorted(items,key=lambda x:x.get('published_iso',''),reverse=True)[:maxn]:
        b=a.get('body',''); body='<p>'+html.escape(b).replace('\n\n','</p><p>').replace('\n','<br>')+'</p>'; prev=b[:500]+('…' if len(b)>500 else '')
        cats='\n'.join(f"      <category>{html.escape(p['name'])}</category>" for p in a.get('tracked_players',[]))
        langs='\n'.join(f"      <category>{html.escape(x)}</category>" for x in a.get('source_languages',[]))
        creator=f"      <dc:creator>{cd(a['author'])}</dc:creator>\n" if a.get('author') else ''
        rows.append(f'''    <item>\n      <title>{cd(a.get('title',''))}</title>\n      <link>{html.escape(a.get('url',''))}</link>\n      <guid isPermaLink="false">{a.get('id','')}</guid>\n      <pubDate>{a.get('published_rfc2822','')}</pubDate>\n      <source>{cd(a.get('source',''))}</source>\n{creator}      <description>{cd(prev)}</description>\n      <content:encoded>{cd(body)}</content:encoded>\n{cats}\n{langs}\n    </item>''')
    return f'''<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/">\n  <channel>\n    <title>{cd(title)}</title>\n    <link>{html.escape(site)}</link>\n    <description>{cd(desc)}</description>\n    <lastBuildDate>{format_datetime(datetime.now(timezone.utc))}</lastBuildDate>\n{chr(10).join(rows)}\n  </channel>\n</rss>'''

def outputs(arts,c):
    DOCS.mkdir(exist_ok=True); PF.mkdir(parents=True,exist_ok=True); m=c['settings']['max_feed_items']; site=c['feed']['site_url']
    (DOCS/'feed.xml').write_text(rss(arts,c['feed']['title'],c['feed']['description'],site,m),encoding='utf-8')
    for p in c['players']:
        xs=[a for a in arts if any(t.get('name')==p['name'] for t in a.get('tracked_players',[]))]
        (PF/f"{slug(p['name'])}.xml").write_text(rss(xs,f"{p['name']} — Mexicanos en Europa",f"Noticias que mencionan a {p['name']} ({p['club']}). Sin filtro de idioma.",site,m),encoding='utf-8')
    cards=[]
    for a in sorted(arts,key=lambda x:x.get('published_iso',''),reverse=True)[:200]:
        names=', '.join(p['name'] for p in a.get('tracked_players',[])); clubs=', '.join(sorted({p['club'] for p in a.get('tracked_players',[])})); langs=', '.join(a.get('source_languages',[])) or 'No informado'; via=', '.join(a.get('discovery_sources',[]))
        cards.append(f'<article><h2><a href="{html.escape(a.get("url",""))}" target="_blank">{html.escape(a.get("title",""))}</a></h2><p><strong>{html.escape(names)}</strong> · {html.escape(clubs)}</p><p>{html.escape(a.get("source",""))} · {html.escape(a.get("published_display",""))}</p><p>Idioma: {html.escape(langs)} · Vía: {html.escape(via)}</p></article>')
    links=''.join(f'<li><a href="players/{slug(p["name"])}.xml">{html.escape(p["name"])}</a> — {html.escape(p["club"])}</li>' for p in c['players'])
    page=f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mexicanos en Europa</title><style>body{{font-family:Arial,sans-serif;max-width:1050px;margin:40px auto;padding:0 20px;line-height:1.5}}article{{padding:14px 0;border-bottom:1px solid #ddd}}h2{{font-size:20px;margin-bottom:5px}}p{{margin:5px 0}}.notice{{background:#f5f5f5;padding:14px;border-radius:8px}}</style></head><body><h1>Mexicanos en Europa</h1><p class="notice">Monitor multilingüe: busca menciones de los nombres de los jugadores y no descarta artículos por idioma.</p><p>RSS general: <a href="feed.xml">feed.xml</a></p><h2>Feeds por jugador</h2><ul>{links}</ul><h2>Noticias recientes</h2>{''.join(cards) if cards else '<p>Aún no hay artículos.</p>'}</body></html>'''
    (DOCS/'index.html').write_text(page,encoding='utf-8')

def main():
    c=cfg(); arts=load(); existing={a.get('url'):a for a in arts if a.get('url')}; cutoff=datetime.now(timezone.utc)-timedelta(hours=c['settings']['max_age_hours']); new=0
    print('MEXICANOS EN EUROPA'); print('Players:',len(c['players']))
    for p in c['players']:
        print(f"\nPLAYER: {p['name']} — {p['club']}"); cand=gdelt(p,c)+google(p,c); uniq={}
        for x in cand:
            if x['published']>=cutoff and x['url'] not in uniq: uniq[x['url']]=x
        print('  Unique recent candidates:',len(uniq))
        for x in uniq.values():
            u=x['url']
            if u in existing: merge(existing[u],p,x); continue
            print('  Fetching:',x.get('title','')[:90]); e=extract(u)
            if not e or len(e['body'])<c['settings']['minimum_body_characters']: print('    Skipped: body unavailable/too short'); time.sleep(c['settings']['delay_between_articles_seconds']); continue
            txt=(e.get('title') or '')+'\n'+e['body']
            if not mentions(txt,p['name']): print('    Skipped: player name not in extracted page'); time.sleep(c['settings']['delay_between_articles_seconds']); continue
            tracked=detected(txt,c['players']) or [{'name':p['name'],'club':p['club'],'group':p['group']}]; pub=x['published']
            a={'id':aid(u),'title':e.get('title') or x.get('title') or u,'source':x.get('source') or domain(u),'author':e.get('author',''),'url':u,'published_iso':pub.isoformat(),'published_rfc2822':format_datetime(pub),'published_display':pub.strftime('%Y-%m-%d %H:%M UTC'),'body':e['body'],'tracked_players':tracked,'source_languages':[x['language']] if x.get('language') else [],'source_countries':[x['country']] if x.get('country') else [],'discovery_sources':[x['via']],'collected_iso':datetime.now(timezone.utc).isoformat()}
            arts.append(a); existing[u]=a; new+=1; time.sleep(c['settings']['delay_between_articles_seconds'])
    arts=sorted(arts,key=lambda a:a.get('published_iso',''),reverse=True)[:c['settings']['max_stored_articles']]; save(arts); outputs(arts,c)
    print('\nDONE'); print('New:',new); print('Stored:',len(arts)); print('RSS: docs/feed.xml')
if __name__=='__main__': main()
