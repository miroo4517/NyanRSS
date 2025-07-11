import discord
import feedparser
import os
import yaml
import asyncio
import google.generativeai as genai
import re
import time
import datetime
import PIL.Image
import requests
from dotenv import load_dotenv
from discord import Embed, Color, utils
from urllib.parse import urlparse
from io import BytesIO

load_dotenv()
intents = discord.Intents.all()
client = discord.Client(intents=intents)

DISCORD_CHANNEL_IDS = []
DISCORD_BOT_TOKEN = ""
RSS_FEED_URLS = []
GOOGLE_API_KEY = ""
site_color_map = {}

def load_initial_config():
    global DISCORD_CHANNEL_IDS, DISCORD_BOT_TOKEN, RSS_FEED_URLS, GOOGLE_API_KEY, site_color_map
    try:
        channel_ids_str = os.getenv('DISCORD_CHANNEL_IDS', '')
        if channel_ids_str:
            DISCORD_CHANNEL_IDS = list(map(int, channel_ids_str.split(',')))
        else:
            DISCORD_CHANNEL_IDS = []

        DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
        RSS_FEED_URLS = os.getenv('RSS_FEED_URLS', '').split(",")
        GOOGLE_API_KEY = os.getenv('GEMINI_API_KEY')

        SITE_COLORS_STR = os.getenv('SITE_COLORS', '')
        site_color_map = {}
        if SITE_COLORS_STR:
            pairs = SITE_COLORS_STR.split(',')
            for pair in pairs:
                if ':' in pair:
                    try:
                        url, hex_color = pair.strip().rsplit(':', 1)
                        if re.match(r'^#[0-9a-fA-F]{6}$', hex_color):
                            site_color_map[url.strip()] = hex_color.strip()
                        else:
                            print(f"경고: .env의 SITE_COLORS에 잘못된 HEX 코드 형식 발견 - '{pair.strip()}' 건너뜁니다.")
                    except ValueError:
                        print(f"경고: .env의 SITE_COLORS 형식 오류 - '{pair.strip()}' 건너뜁니다.")
                else:
                    print(f"경고: .env의 SITE_COLORS 형식 오류 (콜론 없음) - '{pair.strip()}' 건너뜁니다.")
        print(f"사이트별 색상 설정 로드: {len(site_color_map)}개")

        if not all([DISCORD_BOT_TOKEN, RSS_FEED_URLS, GOOGLE_API_KEY]):
            raise ValueError("필수 환경 변수 중 일부가 설정되지 않았습니다 (DISCORD_BOT_TOKEN, RSS_FEED_URLS, GEMINI_API_KEY 확인)")

        print(f"초기 채널 ID 로드: {DISCORD_CHANNEL_IDS}")
        return True

    except ValueError as e:
        print(f"환경 변수 로드 오류: {e}")
        return False
    except Exception as e:
        print(f"설정 로드 중 예상치 못한 오류: {e}")
        return False

EMOJI = "\U0001F4F0"
sent_articles_file = "sent_articles.yaml"
yaml_lock = asyncio.Lock()
max_keep = 5000
model = None

def setup_gemini():
    global model
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        generation_config = {
            "temperature": 0.7, "top_p": 1, "top_k": 1, "max_output_tokens": 256,
        }
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
        model = genai.GenerativeModel(model_name="gemini-1.5-flash",
                                      generation_config=generation_config,
                                      safety_settings=safety_settings)
        print("Gemini 모델 설정 완료.")
        return True
    except Exception as e:
        print(f"Gemini 설정 중 오류 발생: {e}")
        return False

def clean_html(raw_html):
    if not raw_html: return ""
    processed_html = re.sub('<br\s*/?>', '\n', raw_html, flags=re.IGNORECASE)
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', processed_html)
    cleantext = ' '.join(cleantext.split())
    return cleantext.strip()

async def summarize_article(content, image_pil=None):
    if not model:
        return "Gemini 모델이 설정되지 않았습니다."
    if not content and not image_pil:
         return "요약할 내용이나 이미지가 없습니다."
    if content and len(content) < 30 and not image_pil:
        return "요약할 내용이 충분하지 않습니다."

    try:
        prompt = f"""너는 이제부터 기사 요약하는 고양이다냥! 다음 뉴스기사 내용과 이미지를 보고 한국어로 간결하게 5~7문장 이내로, 최대한 줄바꿈 없이, 반말(중요)로 요약해달라냥! 무조건 말 끝에 냥을 붙이고 고양이 이모티콘도 자주 쓰고 고양이답게 말투도 엄청 귀여워야 한다냥! 가능하다면 배경지식도 넣어서 요약해달라냥! 항상 요약은 냐옹!으로 시작하고 마지막에는 냥냥!으로 끝나야 한다냥!:

        ---
        {content[:1500] if content else "텍스트 내용 없음"}
        ---

        요약:"""

        api_content = []
        if content:
            api_content.append(prompt)
        if image_pil:
            api_content.append(image_pil)
            if not content:
                 api_content.insert(0, "이 이미지를 보고 한국어로 간결하게 5~7문장 이내로, 최대한 줄바꿈 없이, 반말(중요)로 설명해달라냥! 무조건 말 끝에 냥을 붙이고 고양이 이모티콘도 자주 쓰고 고양이답게 말투도 엄청 귀여워야 한다냥! 항상 설명은 냐옹!으로 시작하고 마지막에는 냥냥!으로 끝나야 한다냥! 설명:")

        if not api_content:
             return "API로 보낼 내용이 없습니다."

        response = await model.generate_content_async(api_content)

        if not response.candidates:
            print("경고: Gemini API 응답에 후보가 없습니다. 안전 설정 또는 입력 문제일 수 있습니다.")
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                print(f"   프롬프트 피드백: {response.prompt_feedback}")
            return "기사 요약 중 문제가 발생했습니다. (No candidates)"

        summary = response.text.strip() if response.candidates else None

        if not summary:
            print("경고: Gemini API가 빈 요약을 반환했습니다.")
            return "기사 내용을 요약할 수 없습니다."

        summary = summary.replace(''', "'").replace(''', "'")

        return summary
    except Exception as e:
        print(f"Gemini API 호출 중 오류 발생 ({type(e).__name__}): {e}")
        if "400" in str(e) and "image" in str(e).lower():
             print("   -> 이미지 관련 API 오류일 수 있습니다. 이미지 형식이나 크기를 확인하세요.")
             return f"이미지 처리 중 API 오류가 발생했습니다: {type(e).__name__}"
        return f"기사 요약 중 API 오류가 발생했습니다: {type(e).__name__}"

async def load_sent_articles(channel_id_str):
    async with yaml_lock:
        if os.path.exists(sent_articles_file):
            try:
                with open(sent_articles_file, "r", encoding='utf-8') as f:
                    all_sent_data = yaml.safe_load(f) or {}
                sent_articles = all_sent_data.get(channel_id_str, [])
                if not isinstance(sent_articles, list):
                    print(f"경고: 채널 {channel_id_str}의 sent_articles 데이터가 리스트가 아닙니다. 초기화합니다.")
                    return []
                print(f"채널 {channel_id_str}: 기존 {len(sent_articles)}개 기사 링크 로드됨")
                return sent_articles
            except yaml.YAMLError as e:
                print(f"YAML 파일 파싱 오류 ({sent_articles_file}): {e}. 파일을 백업하고 새로 시작합니다.")
                try:
                    os.rename(sent_articles_file, f"{sent_articles_file}.bak_{int(time.time())}")
                except OSError as backup_err:
                    print(f"   오류: YAML 파일 백업 실패: {backup_err}")
                return []
            except Exception as e:
                print(f"YAML 파일 로드 오류: {e}")
                return []
        else:
            print("sent_articles.yaml 파일을 찾을 수 없어 새로 생성합니다.")
            return []

async def save_sent_article(channel_id_str, article_link):
    async with yaml_lock:
        try:
            all_sent_data = {}
            if os.path.exists(sent_articles_file):
                try:
                    with open(sent_articles_file, "r", encoding='utf-8') as f:
                        all_sent_data = yaml.safe_load(f) or {}
                        if not isinstance(all_sent_data, dict):
                            print(f"경고: {sent_articles_file} 파일 내용이 딕셔너리가 아닙니다. 새로 생성합니다.")
                            all_sent_data = {}
                except yaml.YAMLError as e:
                       print(f"YAML 파일 파싱 오류 ({sent_articles_file}) 저장 시: {e}. 파일을 백업하고 새로 시작합니다.")
                       try:
                           os.rename(sent_articles_file, f"{sent_articles_file}.bak_{int(time.time())}")
                       except OSError as backup_err:
                           print(f"   오류: YAML 파일 백업 실패: {backup_err}")
                       all_sent_data = {}

            channel_key = str(channel_id_str)
            channel_sent_list = all_sent_data.get(channel_key, [])
            if not isinstance(channel_sent_list, list):
                print(f"경고: 파일 저장 중 채널 {channel_key} 데이터가 리스트가 아님. 재생성.")
                channel_sent_list = []

            if article_link not in channel_sent_list:
                   channel_sent_list.append(article_link)

            if len(channel_sent_list) > max_keep:
                original_count = len(channel_sent_list)
                channel_sent_list = channel_sent_list[-max_keep:]
                print(f"채널 {channel_key}: 오래된 기사 링크 정리 (파일 저장 시). {original_count} -> {len(channel_sent_list)}개 유지.")

            all_sent_data[channel_key] = channel_sent_list

            with open(sent_articles_file, "w", encoding='utf-8') as f:
                yaml.dump(all_sent_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            print(f"채널 {channel_key}: 기사 '{article_link}' 전송 완료 및 YAML 저장됨.")

        except Exception as e:
            print(f"sent_articles.yaml 파일 저장 중 오류 발생 (개별 저장): {e}")

def normalize_url(url):
    """URL을 정규화하여 중복을 방지합니다."""
    # URL 파라미터와 프래그먼트 제거
    normalized = url.split('?')[0].split('#')[0]
    # 끝의 슬래시 제거
    normalized = normalized.rstrip('/')
    return normalized

def normalize_title(title):
    """제목을 정규화하여 유사도 비교에 사용합니다."""
    # HTML 엔티티 치환
    title = title.replace('&#8216;', "'").replace('&#8217;', "'")
    title = title.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    # 특수문자 제거하고 소문자로 변환
    normalized = re.sub(r'[^\w\s]', ' ', title.lower())
    # 여러 공백을 하나로 합치고 앞뒤 공백 제거
    normalized = ' '.join(normalized.split())
    return normalized

def calculate_title_similarity(title1, title2):
    """두 제목의 유사도를 계산합니다 (0.0 ~ 1.0)."""
    if len(title1) < 5 or len(title2) < 5:
        return 0.0
    
    words1 = set(title1.split())
    words2 = set(title2.split())
    
    if not words1 or not words2:
        return 0.0
    
    # 자카드 유사도 계산
    intersection = words1 & words2
    union = words1 | words2
    
    return len(intersection) / len(union)

async def fetch_feed(channel, site_colors, current_rss_feeds):
    channel_id_str = str(channel.id)
    sent_articles = await load_sent_articles(channel_id_str)
    sent_articles_set = set(sent_articles)
    
    # 현재 세션에서 처리된 기사들을 추적 (중복 방지)
    current_session_processed = set()
    current_session_titles = {}  # URL -> 정규화된 제목

    new_articles_processed_count = 0

    for rss_feed_url in current_rss_feeds:
        if not rss_feed_url: continue

        print(f"채널 {channel_id_str}: '{rss_feed_url}' 피드 파싱 중...")
        feed_start_time = time.monotonic()
        try:
            feed = feedparser.parse(rss_feed_url, agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 NyanRSS/1.0')
            if feed.bozo and isinstance(feed.bozo_exception, (feedparser.CharacterEncodingOverride, feedparser.NonXMLContentType)):
                   print(f"   경고: '{rss_feed_url}' 파싱 경고: {feed.bozo_exception}")
            elif feed.bozo:
                   raise feed.bozo_exception
        except Exception as e:
            print(f"   오류: '{rss_feed_url}' 피드 파싱 중 심각한 오류: {e}")
            continue
        parse_duration = time.monotonic() - feed_start_time
        print(f"   파싱 완료 ({len(feed.entries)}개 항목). 소요 시간: {parse_duration:.2f}초")

        if not feed.entries:
            print(f"   '{rss_feed_url}' 피드에 항목이 없습니다.")
            continue

        for entry in feed.entries:
            article_id = getattr(entry, 'link', None)
            if not article_id:
                   article_id = getattr(entry, 'id', None)
            if not article_id:
                   print(f"   경고: 링크 또는 ID 없는 항목 발견. 건너뜁니다. (제목: {getattr(entry, 'title', 'N/A')})")
                   continue

            # URL 정규화
            normalized_url = normalize_url(article_id)
            
            # 이미 처리된 기사인지 확인 (원본 URL과 정규화된 URL 모두 확인)
            if (article_id in sent_articles_set or 
                normalized_url in sent_articles_set or
                article_id in current_session_processed or 
                normalized_url in current_session_processed):
                print(f"   이미 처리된 항목: {article_id}")
                continue

            # 제목 기반 중복 체크
            article_title = getattr(entry, 'title', '제목 없음').strip()
            normalized_title = normalize_title(article_title)
            
            # 현재 세션에서 유사한 제목이 있는지 확인
            is_duplicate = False
            for processed_url, processed_title in current_session_titles.items():
                similarity = calculate_title_similarity(normalized_title, processed_title)
                if similarity > 0.8:  # 80% 이상 유사하면 중복으로 간주
                    print(f"   유사한 제목의 기사 이미 처리됨 (유사도: {similarity:.2f}): {article_title}")
                    is_duplicate = True
                    break
            
            if is_duplicate:
                continue

            new_articles_processed_count += 1
            print(f"   >> 새 기사 발견: '{article_title}' ({rss_feed_url})")
            
            # 현재 세션 처리 목록에 추가
            current_session_processed.add(article_id)
            current_session_processed.add(normalized_url)
            current_session_titles[article_id] = normalized_title

            article_content = getattr(entry, 'summary', getattr(entry, 'description', ""))
            article_content_text = clean_html(article_content)

            image_url = None
            if hasattr(entry, 'enclosures'):
                for enclosure in entry.enclosures:
                    if enclosure.get('type', '').startswith('image/'):
                        image_url = enclosure.get('href')
                        if image_url:
                            print(f"       이미지 발견 (enclosure): {image_url[:50]}...")
                            break
            if not image_url and hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                if isinstance(entry.media_thumbnail, list) and len(entry.media_thumbnail) > 0:
                    thumb_info = entry.media_thumbnail[0]
                    if isinstance(thumb_info, dict) and 'url' in thumb_info:
                        image_url = thumb_info['url']
                        if image_url:
                            print(f"       이미지 발견 (media_thumbnail): {image_url[:50]}...")
            if not image_url and hasattr(entry, 'media_content') and entry.media_content:
                if isinstance(entry.media_content, list) and len(entry.media_content) > 0:
                    for media_item in entry.media_content:
                        if isinstance(media_item, dict) and 'url' in media_item:
                            potential_url = media_item['url']
                            is_image = False
                            if media_item.get('type', '').startswith('image/'): is_image = True
                            elif media_item.get('medium') == 'image': is_image = True
                            elif potential_url and media_item.get('width') and int(media_item['width']) > 200:
                                   is_image = True

                            if is_image and potential_url:
                                image_url = potential_url
                                print(f"       이미지 발견 (media_content): {image_url[:50]}...")
                                break

            pil_image = None
            if image_url:
                try:
                    print(f"       이미지 다운로드 시도: {image_url}")
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 NyanRSS/1.0'}
                    response = requests.get(image_url, headers=headers, stream=True, timeout=10)
                    response.raise_for_status()
                    image_bytes = BytesIO(response.content)
                    pil_image = PIL.Image.open(image_bytes)
                    print(f"       이미지 로드 성공: {pil_image.format}, {pil_image.size}")
                except requests.exceptions.RequestException as req_err:
                    print(f"       오류: 이미지 다운로드 실패 ({image_url}): {req_err}")
                    image_url = None
                except PIL.UnidentifiedImageError:
                    print(f"       오류: PIL이 이미지 파일을 식별할 수 없음 ({image_url}). 이미지 형식이 아니거나 손상되었을 수 있습니다.")
                    image_url = None
                except Exception as img_err:
                    print(f"       오류: 이미지 처리 중 예상치 못한 오류 ({image_url}): {img_err}")
                    image_url = None

            summary = "요약 정보를 가져올 수 없었습니다."
            if article_content_text or pil_image:
                print("       Gemini API로 요약 요청 중...")
                summary_start_time = time.monotonic()
                summary = await summarize_article(article_content_text, pil_image)
                summary_duration = time.monotonic() - summary_start_time
                print(f"       요약 완료. 소요 시간: {summary_duration:.2f}초")
            else:
                print("       요약할 내용이나 이미지가 없어 Gemini 호출을 건너뜁니다.")
                summary = "기사 본문 내용이나 이미지가 없어 요약할 수 없습니다."

            try:
                embed_color = Color.blue()
                parsed_uri = urlparse(rss_feed_url)
                base_url = f"{parsed_uri.scheme}://{parsed_uri.netloc}"
                hex_color_str = site_color_map.get(rss_feed_url) or site_color_map.get(base_url)

                if hex_color_str:
                    try:
                        color_value = int(hex_color_str.lstrip('#'), 16)
                        embed_color = Color(color_value)
                    except ValueError:
                        print(f"   경고: '{rss_feed_url}'에 대한 HEX 코드 '{hex_color_str}' 변환 실패. 기본 색상 사용.")

                embed = Embed(
                    title=f"{EMOJI} {article_title}",
                    url=article_id,
                    color=embed_color
                )

                summary_to_display = summary
                max_summary_length = 1024
                if len(summary) > max_summary_length:
                    cutoff = max_summary_length - len("... (내용 축약됨)")
                    summary_to_display = f"{summary[:cutoff]}... (내용 축약됨)"
                    print("       경고: 요약 내용이 너무 길어 Embed 필드에서 잘렸습니다.")

                if summary:
                    embed.add_field(name="AI 냥냥 요약!", value=summary_to_display, inline=False)

                if image_url:
                    embed.set_image(url=image_url)
                    print(f"최종 선택된 이미지 URL (Embed용): {image_url}")
                else:
                    print("       이 항목에서 이미지를 찾지 못했거나 로드에 실패했습니다.")

                published_dt = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published_dt = datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc)
                        kst = datetime.timezone(datetime.timedelta(hours=9))
                        published_dt_kst = published_dt.astimezone(kst)
                        embed.timestamp = published_dt_kst
                    except Exception as e:
                        print(f"       발행 시각 변환 오류: {e}")
                        embed.timestamp = utils.utcnow()
                else:
                    embed.timestamp = utils.utcnow()

                feed_title = getattr(feed.feed, 'title', rss_feed_url)
                embed.set_footer(text=f"{feed_title}에서 불러온 정보다냥!")

                await channel.send(embed=embed)
                print("       >> Embed 전송 성공.")

                # 전송 성공 후에만 저장 (메모리와 파일 동기화 보장)
                await save_sent_article(channel_id_str, article_id)
                sent_articles_set.add(article_id)
                sent_articles_set.add(normalized_url)  # 정규화된 URL도 추가

                await asyncio.sleep(1.5)

            except discord.Forbidden:
                print("   오류: 채널에 메시지(Embed)를 보낼 권한이 없습니다.")
            except discord.HTTPException as e:
                print(f"   오류: 채널 메시지(Embed) 전송 중 Discord API 오류: {e.status} - {e.text}")
                if e.status == 429:
                    retry_after = getattr(e, 'retry_after', 5.0)
                    print(f"   Discord Rate Limit 감지. {retry_after:.1f}초 대기 후 계속합니다.")
                    await asyncio.sleep(retry_after)
            except Exception as e:
                print(f"   오류: 메시지(Embed) 전송 또는 처리 중 예상치 못한 오류: {e}")

            if new_articles_processed_count > 0 and new_articles_processed_count % 15 == 0:
                   print(f"   15개 항목 처리 후 잠시 대기...")
                   await asyncio.sleep(60)

    print(f"채널 {channel_id_str}: 총 {new_articles_processed_count}개의 새 기사 처리 완료.")

@client.event
async def on_ready():
    global DISCORD_CHANNEL_IDS, RSS_FEED_URLS, site_color_map

    print(f"봇 로그인: {client.user.name} (ID: {client.user.id})")

    if not load_initial_config():
        print("초기 설정 로드 실패. 봇을 종료합니다.")
        await client.close()
        return

    if not setup_gemini():
        print("Gemini 모델 설정 실패. 요약 기능 없이 계속하거나 봇을 종료합니다.")

    print(f"등록된 채널 ID: {DISCORD_CHANNEL_IDS}")
    print(f"등록된 RSS 피드 수: {len(RSS_FEED_URLS)}")
    print(f"로드된 사이트별 색상 수: {len(site_color_map)}")
    print("-" * 20)
    print("봇이 준비되었습니다. 10초 후 첫 RSS 피드 확인을 시작합니다.")
    await asyncio.sleep(10)

    while True:
        print("-" * 20)
        start_time = time.monotonic()
        print(f"{datetime.datetime.now()} - RSS 피드 확인 주기 시작...")

        current_channel_ids_to_process = list(DISCORD_CHANNEL_IDS)
        current_rss_feeds_to_process = list(RSS_FEED_URLS)
        current_site_colors = dict(site_color_map)

        if not current_channel_ids_to_process:
            print("   처리할 채널이 없습니다. 대기합니다.")
        else:
            active_tasks = []
            for channel_id in current_channel_ids_to_process:
                channel = client.get_channel(channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    print(f"   -> 채널 '{channel.name}' (ID: {channel.id}) 작업 생성 중...")
                    task = asyncio.create_task(fetch_feed(channel, current_site_colors, current_rss_feeds_to_process), name=f"fetch_feed_{channel_id}")
                    active_tasks.append(task)
                elif channel:
                       print(f"경고: 채널 ID {channel_id}는 텍스트 채널이 아닙니다: {type(channel)}")
                else:
                       print(f"경고: 채널 ID {channel_id}를 찾을 수 없거나 접근할 수 없습니다. (봇이 해당 서버에 있고 권한이 있는지 확인)")

            if active_tasks:
                results = await asyncio.gather(*active_tasks, return_exceptions=True)
                for i, result in enumerate(results):
                       if isinstance(result, Exception):
                           task_name = active_tasks[i].get_name()
                           print(f"오류: 작업 '{task_name}' 실행 중 예외 발생: {type(result).__name__} - {result}")

                print(f"   -> 모든 채널 작업 완료 ({len(active_tasks)}개)")
            else:
                print("   -> 처리할 유효한 채널이 없습니다.")

        print(f"{datetime.datetime.now()} - .env 파일에서 설정 다시 로드 시도...")
        try:
            dotenv_path = load_dotenv(override=True, verbose=False)
            if dotenv_path:
                new_channel_ids_str = os.getenv('DISCORD_CHANNEL_IDS', '')
                new_channel_ids = []
                if new_channel_ids_str:
                    try:
                        new_channel_ids = list(map(int, new_channel_ids_str.split(',')))
                    except ValueError:
                        print("   오류: .env의 DISCORD_CHANNEL_IDS 형식이 잘못되었습니다 (숫자 목록이어야 함). 채널 ID 업데이트 실패.")
                        new_channel_ids = list(DISCORD_CHANNEL_IDS)

                if new_channel_ids != DISCORD_CHANNEL_IDS:
                    print(f"   성공: DISCORD_CHANNEL_IDS 업데이트됨: {new_channel_ids}")
                    DISCORD_CHANNEL_IDS = new_channel_ids
                else:
                    print("   정보: DISCORD_CHANNEL_IDS 변경 없음.")

                new_rss_urls_str = os.getenv('RSS_FEED_URLS', '')
                new_rss_urls = [url.strip() for url in new_rss_urls_str.split(',') if url.strip()]
                if new_rss_urls != RSS_FEED_URLS:
                    print(f"   성공: RSS_FEED_URLS 업데이트됨 (총 {len(new_rss_urls)}개)")
                    RSS_FEED_URLS = new_rss_urls
                else:
                    print("   정보: RSS_FEED_URLS 변경 없음.")

                new_site_colors_str = os.getenv('SITE_COLORS', '')
                new_site_color_map = {}
                if new_site_colors_str:
                    pairs = new_site_colors_str.split(',')
                    for pair in pairs:
                        if ':' in pair:
                            try:
                                url, hex_color = pair.strip().rsplit(':', 1)
                                if re.match(r'^#[0-9a-fA-F]{6}$', hex_color):
                                    new_site_color_map[url.strip()] = hex_color.strip()
                                else:
                                    print(f"   경고: .env의 SITE_COLORS 업데이트 중 잘못된 HEX 코드 형식 발견 - '{pair.strip()}' 건너뜁니다.")
                            except ValueError:
                                print(f"   경고: .env의 SITE_COLORS 업데이트 중 형식 오류 - '{pair.strip()}' 건너뜁니다.")
                        else:
                            print(f"   경고: .env의 SITE_COLORS 업데이트 중 형식 오류 (콜론 없음) - '{pair.strip()}' 건너뜁니다.")

                if new_site_color_map != site_color_map:
                       print(f"   성공: SITE_COLORS 업데이트됨 (총 {len(new_site_color_map)}개)")
                       site_color_map = new_site_color_map
                else:
                       print("   정보: SITE_COLORS 변경 없음.")

            else:
                 print("   정보: .env 파일을 찾을 수 없거나 로드되지 않았습니다. 기존 설정 유지.")

        except Exception as e:
            print(f"   오류: .env 파일 다시 로드 또는 처리 중 오류 발생: {e}. 기존 설정 유지.")

        end_time = time.monotonic()
        print(f"{datetime.datetime.now()} - RSS 피드 확인 주기 완료 (총 소요 시간: {end_time - start_time:.2f}초)")

        wait_time = 600
        print(f"다음 확인까지 {wait_time // 60}분 대기...")
        await asyncio.sleep(wait_time)

if __name__ == "__main__":
    print("봇 시작 중...")
    if not load_initial_config():
        print("필수 환경 변수 로드 실패. .env 파일을 확인하세요.")
        exit()
    if not DISCORD_BOT_TOKEN:
        print("오류: DISCORD_BOT_TOKEN이 설정되지 않았습니다.")
        exit()

    try:
        client.run(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        print("오류: 잘못된 디스코드 봇 토큰입니다.")
    except discord.PrivilegedIntentsRequired:
        print("오류: Privileged Intents가 활성화되지 않았습니다.")
        print("Discord 개발자 포털에서 봇의 Privileged Gateway Intents (특히 Message Content Intent)를 확인/활성화하세요.")
    except Exception as e:
        print(f"봇 실행 중 심각한 오류 발생: {e}")
        import traceback
        traceback.print_exc()
