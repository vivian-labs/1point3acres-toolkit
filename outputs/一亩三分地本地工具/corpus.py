"""Offline extraction and selection of sourced journal excerpts. Never fetch or submit text."""
import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from settings import CHECKIN_MOOD_DEFAULT, MOOD_PHRASE_MAX_LENGTH, CORPUS_POETRY_SHARE, JOURNAL_STYLE


FORMAT = 1
FILTER_VERSION = 1
MAX_BYTES = 4_000_000
SOURCE_REPOS = {
    'https://github.com/common-voice/common-voice': 'CC0-1.0',
    'https://github.com/moztw/cc0-sentences': 'CC0-1.0',
    'https://github.com/chinese-poetry/chinese-poetry': 'MIT',
}
# Restrict modern text to general reflections and intentions, rather than biographies,
# replies, news, claims about the member's day, or instructions embedded in source data.
TOPICS = re.compile(r'生活|人生|時間|时间|努力|學習|学习|休息|安靜|安静|心情|快樂|快乐|希望|耐心|堅持|坚持|夢想|梦想|開心|开心|放鬆|放松|慢慢|自然|陽光|阳光|微笑|平靜|平静|忙碌|幸福|勇氣|勇气|輕鬆|轻松|疲|懶|懒|舒服|悠閒|悠闲|無聊|无聊|難過|难过|認真|认真|有趣|美好|珍惜|隨意|随意')
MODERN_START = re.compile(r'^(?:希望|願|愿|想|生活|人生|時間|时间|日子|每天|偶爾|偶尔|有時|有时|不必|不用|不想|不急|別|别|把|讓|让|給|给|慢|保持|繼續|继续|好好|努力|休息|需要|喜歡|喜欢|學習|学习|放|可以|也許|也许|或許|或许|先|其實|其实|只|平|珍惜|有些|有點|有点|對自己|对自己|再|忙|隨|随|認真|认真|堅持|坚持|一切|一生|一點|一点|幸福|美好|快樂|快乐|開心|开心|輕鬆|轻松|安靜|安静|疲|悠閒|悠闲|微笑|自在|舒服|無聊|无聊|多一|多點|多点|少一|少點|少点)')
BLOCKED = re.compile(r'[A-Za-z0-9@#<>《》「」『』“”"：:]|https|政府|政治|總統|总统|國家|国家|民主|黨|党|選舉|选举|立委|臺灣|台湾|中國|中国|憲法|宪法|宗教|上帝|佛|癌|患者|治療|治疗|死|殺|杀|性愛|性爱|性交|法院|法律|股份|公司|基金|大學|大学|學校|学校|醫院|医院|防控|疫|法案|法院|住址|地址|詐騙|诈骗|邪惡|邪恶|幹|操|屁|屌|弱智|蠢|淫|妓|他|她|它|你|妳|您|我們|我们|昨日|昨天|去年|生日|男朋友|女朋友|老公|老婆|媽媽|妈妈|爸爸|女兒|女儿|演算法|算法|技術|技术|程式|程序|欄位|字段|字幕|精緻澱粉|精致淀粉|機長|机长|遊客|游客|協作|协作|保留|排序|會議|会议|展覽|展览|看展|人民|全國|全国|自動化|自动化|貓娘|猫娘|究極|究极|致富|記憶|记忆|同學|同学|廁所|厕所|問題|问题|元素|中心|契約|契约|知識|知识|習慣|习惯|討論|讨论')
NATURE = re.compile(r'[風风花月山水雲云雨雪松竹春秋溪泉林葉叶晴夜光清閒闲靜静遠远夢梦心]')
POETRY_BLOCKED = re.compile(r'君|帝|王|臣|宮|宫|殿|兵|戰|战|血|劍|剑|刀|賊|贼|戎|奴|妾|妓|鬼|神|佛|仙|龍|龙|鳳|凤|酒|醉|墓|墳|坟|哭|泣|恨|愁|怨|毒|病|殘|残|亡|死|殺|杀|獄|狱|虜|虏|奴|貧|贫|饑|饥|飢|淫|□|\?|？')
MODERN_REJECT = re.compile(r'法|罪|危險|危险|中醫|中医|指南|法則|法则|貴族|贵族|電腦|电脑|愛因斯坦|爱因斯坦|三月|晚上|八點|八点|魔法|尺度|右撇子|早自習|早自习|旅客|等車|等车|練習題|练习题|精進|精进|廢片|废片|廢文|废文|偷看|待在|光速|心跳|急遽|零件|螢幕|屏幕|鍵盤|键盘|過程|过程|結帳|结账|發展與|发展与|正職|正职|雖|虽|要的是|的是|將|将|自習|自习|進階|进阶|讀取|读取|作決定|作决定|團隊|团队|時間打|时间打|時間的流動速度|时间的流动速度|分支又合併|分支又合并')


def phrase_key(text):
    # Attribution is metadata, not a way to evade duplicate detection.
    text = unicodedata.normalize('NFKC', text.split('——', 1)[0]).casefold()
    return ''.join(c for c in text if c.isalnum())


def shingles(text):
    key = phrase_key(text)
    return {key[i:i + 3] for i in range(max(1, len(key) - 2))}


def overlaps(text, recent):
    own = shingles(text)
    return any(own == other or (2 * len(own & other) / (len(own) + len(other)) >= .8) for other in recent)


def _source_valid(source):
    return (isinstance(source, dict) and isinstance(source.get('repository'), str)
            and source['repository'] in SOURCE_REPOS
            and SOURCE_REPOS.get(source['repository']) == source.get('license')
            and source.get('kind') in ('modern', 'poetry')
            and (source['kind'] == 'poetry') == (source['repository'] == 'https://github.com/chinese-poetry/chinese-poetry')
            and isinstance(source.get('revision'), str) and re.fullmatch(r'[a-f0-9]{40}', source['revision'])
            and isinstance(source.get('sha256'), str) and re.fullmatch(r'[a-f0-9]{64}', source['sha256'])
            and isinstance(source.get('file'), str) and re.fullmatch(r'[A-Za-z0-9_.-]+', source['file'])
            and source['file'] not in ('.', '..')
            and isinstance(source.get('path'), str) and source['path']
            and not source['path'].startswith(('/', '\\')) and ':' not in source['path']
            and '..' not in source['path'].replace('\\', '/').split('/'))


def _digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def load_corpus(path):
    try:
        raw = Path(path).read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError()
        data = json.loads(raw)
        if (data.get('format') != FORMAT or data.get('filter_version') != FILTER_VERSION
                or not data.get('sources') or not all(_source_valid(s) for s in data['sources'])
                or not isinstance(data.get('entries'), list) or not data['entries']
                or data.get('sha256') != _digest(data['entries'])):
            raise ValueError()
        seen = set()
        for row in data['entries']:
            if not isinstance(row, list) or len(row) != 4:
                raise ValueError()
            text, source, item, paragraph = row
            if (not isinstance(text, str) or text != text.strip() or '\n' in text
                    or not 8 <= len(text) <= MOOD_PHRASE_MAX_LENGTH
                    or type(source) is not int or not 0 <= source < len(data['sources'])
                    or type(item) is not int or item < 0 or type(paragraph) is not int or paragraph < 0):
                raise ValueError()
            key = phrase_key(text)
            if not key or key in seen:
                raise ValueError()
            seen.add(key)
        return [(row[0], data['sources'][row[1]]['kind']) for row in data['entries']]
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('invalid_journal_corpus') from None


def choose_corpus_phrase(mood, corpus, recent, rng):
    if mood == CHECKIN_MOOD_DEFAULT:
        return None
    keys = {phrase_key(text) for text in recent if text}
    prior = [shingles(text) for text in recent if text]
    groups = {kind: [text for text, category in corpus if category == kind and phrase_key(text) not in keys]
              for kind in ('modern', 'poetry')}
    preferred = ('poetry' if rng.random() < CORPUS_POETRY_SHARE else 'modern') if JOURNAL_STYLE == 'mixed' else JOURNAL_STYLE
    # Mixed mode uses the other genre if the preferred group is depleted; explicit modern
    # mode never publishes poetry. The configured weight is a preference, not a quota.
    order = (preferred, 'modern' if preferred == 'poetry' else 'poetry') if JOURNAL_STYLE == 'mixed' else (preferred,)
    for kind in order:
        # Random removal gives an unbiased draw over remaining eligible entries, with a finite bound.
        group = groups[kind]
        while group:
            position = rng.randrange(len(group))
            text = group[position]
            group[position] = group[-1]
            group.pop()
            if not overlaps(text, prior):
                return text
    return None


def extract_entries(source, raw):
    if source['kind'] == 'modern':
        for index, text in enumerate(raw.decode('utf-8-sig').splitlines()):
            text = unicodedata.normalize('NFKC', text).strip()
            if (8 <= len(text) <= 45 and MODERN_START.search(text) and TOPICS.search(text)
                    and not BLOCKED.search(text) and not MODERN_REJECT.search(text)
                    and re.fullmatch(r'[\u3400-\u9fff，。！？、；…—\s]+', text)
                    and not re.search(r'(?:的是|最重要的是|雖|虽|但是|因為|因为|就好|如此|這樣|这样)$', text)):
                yield text, index, 0
    else:
        for index, poem in enumerate(json.loads(raw)):
            author = poem.get('author', '')
            if not re.fullmatch(r'[\u3400-\u9fff]{2,6}', author):
                continue
            for paragraph, text in enumerate(poem.get('paragraphs', [])):
                if (not isinstance(text, str) or not 10 <= len(text) <= 32 or not NATURE.search(text)
                        or BLOCKED.search(text) or POETRY_BLOCKED.search(text)
                        or not re.fullmatch(r'[\u3400-\u9fff，。]+', text)):
                    continue
                yield text + '——' + author, index, paragraph


def build_corpus(sources, inputs):
    if not sources or not all(_source_valid(s) for s in sources):
        raise ValueError('invalid_corpus_sources')
    entries, seen, input_lines = [], set(), 0
    for number, source in enumerate(sources):
        raw = (Path(inputs) / source['file']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source['sha256']:
            raise ValueError('corpus_source_hash_mismatch')
        input_lines += len(raw.decode('utf-8').splitlines()) if source['kind'] == 'modern' else sum(
            len(p.get('paragraphs', [])) for p in json.loads(raw))
        for text, item, paragraph in extract_entries(source, raw):
            key = phrase_key(text)
            if key not in seen:
                entries.append([text, number, item, paragraph])
                seen.add(key)
    return {'format': FORMAT, 'filter_version': FILTER_VERSION, 'sources': sources,
            'input_segments': input_lines, 'entries': entries, 'sha256': _digest(entries)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True, help='JSON array of pinned source descriptors')
    parser.add_argument('--inputs', type=Path, required=True, help='local files, already downloaded and hash-verified')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = build_corpus(json.loads(args.sources.read_text(encoding='utf-8')), args.inputs)
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if not data['entries'] or len(raw) > MAX_BYTES:
        raise ValueError('corpus_empty_or_oversized')
    # Build privately, validate the complete result, then atomically replace the destination.
    temporary = args.output.with_suffix('.tmp')
    try:
        temporary.write_bytes(raw)
        load_corpus(temporary)
        temporary.replace(args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({'input_segments': data['input_segments'], 'entries': len(data['entries']),
                      'styles': {kind: sum(data['sources'][e[1]]['kind'] == kind for e in data['entries'])
                                 for kind in ('modern', 'poetry')}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
