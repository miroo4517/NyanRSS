import discord
import feedparser
import os
from dotenv import load_dotenv
import yaml
import asyncio
import google.generativeai as genai
import re
import time
import datetime
from discord import Embed, Color, utils
from urllib.parse import urlparse

load_dotenv()
intents = discord.Intents.all()
client = discord.Client(intents=intents)

try:
    DISCORD_CHANNEL_IDS = list(map(int, os.getenv('DISCORD_CHANNEL_IDS', '').split(',')))
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

    if not all([DISCORD_CHANNEL_IDS, DISCORD_BOT_TOKEN, RSS_FEED_URLS, GOOGLE_API_KEY]):
        raise ValueError("필수 환경 변수 중 일부가 설정되지 않았습니다 (.env 파일 확인)")
except ValueError as e:
    print(f"환경 변수 로드 오류: {e}")
    exit()

EMOJI = "\U0001F4F0"
sent_articles_file = "sent_articles.yaml"
yaml_lock = asyncio.Lock()

try:
    genai.configure(api_key=GOOGLE_API_KEY)
    generation_config = {
        "temperature": 0.7,
        "top_p": 1,
        "top_k": 1,
        "max_output_tokens": 256,
    }
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
    model = genai.GenerativeModel(model_name="gemini-2.0-flash",
                                  generation_config=generation_config,
                                  safety_settings=safety_settings)
except Exception as e:
    print(f"Gemini 설정 중 오류 발생: {e}")
    exit()

def clean_html(raw_html):
    if not raw_html: return ""
    processed_html = re.sub('<br\s*/?>', '\n', raw_html, flags=re.IGNORECASE)
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', processed_html)
    cleantext = ' '.join(cleantext.split())
    return cleantext.strip()

async def summarize_article(content):
    if not content or len(content) < 30:
        return "요약할 내용이 충분하지 않습니다."
    try:
        prompt = f"""너는 이제부터 기사 요약하는 고양이다냥! 다음 뉴스기사 내용을 한국어로 간결하게 5~7문장 이내로, 최대한 줄바꿈 없이, 반말(중요)로 요약해달라냥! 무조건 말 끝에 냥을 붙이고 고양이 이모티콘도 자주 쓰고 고양이답게 말투도 엄청 귀여워야 한다냥! 가능하다면 배경지식도 넣어서 요약해달라냥! 항상 요약은 냐옹!으로 시작하고 마지막에는 냥냥!으로 끝나야 한다냥!:

        ---
        {content[:1500]}
        ---

        요약:"""

        response = await model.generate_content_async(prompt)

        if not response.candidates:
                print("경고: Gemini API 응답에 후보가 없습니다. 안전 설정 또는 입력 문제일 수 있습니다.")
                if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                    print(f"  프롬프트 피드백: {response.prompt_feedback}")
                return "기사 요약 중 문제가 발생했습니다. (No candidates)"

        summary = response.text.strip() if response.candidates else None

        if not summary:
            print("경고: Gemini API가 빈 요약을 반환했습니다.")
            return "기사 내용을 요약할 수 없습니다."

        summary = summary.replace('’', "'").replace('‘', "'")

        return summary
    except Exception as e:
        print(f"Gemini API 호출 중 오류 발생 ({type(e).__name__}): {e}")
        return f"기사 요약 중 API 오류가 발생했습니다: {type(e).__name__}"


async def fetch_feed(channel, site_colors):
    sent_articles = []
    channel_id_str = str(channel.id)

    async with yaml_lock:
        if os.path.exists(sent_articles_file):
            try:
                with open(sent_articles_file, "r", encoding='utf-8') as f:
                    all_sent_data = yaml.safe_load(f) or {}
                sent_articles = all_sent_data.get(channel_id_str, [])
                if not isinstance(sent_articles, list):
                    print(f"경고: 채널 {channel_id_str}의 sent_articles 데이터가 리스트가 아닙니다. 초기화합니다.")
                    sent_articles = []
                print(f"채널 {channel_id_str}: 기존 {len(sent_articles)}개 기사 링크 로드됨")
            except Exception as e:
                print(f"YAML 파일 로드 오류: {e}")
                sent_articles = []
        else:
            print("sent_articles.yaml 파일을 찾을 수 없어 새로 생성합니다.")
            sent_articles = []

    new_articles_processed_count = 0
    max_keep = 5000

    for rss_feed_url in RSS_FEED_URLS:
        if not rss_feed_url: continue

        print(f"채널 {channel_id_str}: '{rss_feed_url}' 피드 파싱 중...")
        feed_start_time = time.monotonic()
        try:
            feed = feedparser.parse(rss_feed_url, agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 NyanRSS/1.0')
            if feed.bozo and isinstance(feed.bozo_exception, (feedparser.CharacterEncodingOverride, feedparser.NonXMLContentType)):
                 print(f"  경고: '{rss_feed_url}' 파싱 경고: {feed.bozo_exception}")
            elif feed.bozo:
                 raise feed.bozo_exception
        except Exception as e:
            print(f"  오류: '{rss_feed_url}' 피드 파싱 중 심각한 오류: {e}")
            continue
        print(f"  파싱 완료 ({len(feed.entries)}개 항목). 소요 시간: {time.monotonic() - feed_start_time:.2f}초")

        if not feed.entries:
            print(f"  '{rss_feed_url}' 피드에 항목이 없습니다.")
            continue

        for entry in feed.entries:
            if not hasattr(entry, 'link') or not entry.link:
                print(f"  경고: 링크 없는 항목 발견. 건너뜁니다. (제목: {getattr(entry, 'title', 'N/A')})")
                continue

            article_link = entry.link

            if article_link in sent_articles:
                print(f"  이미 처리된 항목: {article_link}")
                continue

            new_articles_processed_count += 1
            article_title = getattr(entry, 'title', '제목 없음').strip().replace('&#8216;', "‘").replace('&#8217;', "’")
            print(f"  >> 새 기사 발견: '{article_title}' ({rss_feed_url})")

            article_content = getattr(entry, 'summary', getattr(entry, 'description', ""))
            article_content_text = clean_html(article_content)

            summary = "요약 정보를 가져올 수 없었습니다."
            if article_content_text:
                print("       Gemini API로 요약 요청 중...")
                summary_start_time = time.monotonic()
                summary = await summarize_article(article_content_text)
                print(f"       요약 완료. 소요 시간: {time.monotonic() - summary_start_time:.2f}초")
            else:
                print("       요약할 내용이 없어 Gemini 호출을 건너뜁니다.")
                summary = "기사 본문 내용이 없어 요약할 수 없습니다."

            sent_articles.append(article_link)

            try:
                embed_color = Color.blue()
                hex_color_str = site_colors.get(rss_feed_url)

                if hex_color_str:
                    try:
                        color_value = int(hex_color_str.lstrip('#'), 16)
                        embed_color = Color(color_value)
                    except ValueError:
                        print(f"  경고: '{rss_feed_url}'에 대한 HEX 코드 '{hex_color_str}' 변환 실패. 기본 색상 사용.")

                embed = Embed(
                    title=f"{EMOJI} {article_title}",
                    url=article_link,
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

                image_url = None

                if hasattr(entry, 'enclosures'):
                    for enclosure in entry.enclosures:
                        if enclosure.get('type', '').startswith('image/'):
                            image_url = enclosure.get('href')
                            if image_url:
                                print(f"      이미지 발견 (enclosure): {image_url[:50]}...")
                                break

                if not image_url and hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                    if isinstance(entry.media_thumbnail, list) and len(entry.media_thumbnail) > 0:
                        thumb_info = entry.media_thumbnail[0]
                        if isinstance(thumb_info, dict) and 'url' in thumb_info:
                            image_url = thumb_info['url']
                            if image_url:
                                print(f"      이미지 발견 (media_thumbnail): {image_url[:50]}...")

                if not image_url and hasattr(entry, 'media_content') and entry.media_content:
                    if isinstance(entry.media_content, list) and len(entry.media_content) > 0:
                        for media_item in entry.media_content:
                            if isinstance(media_item, dict) and 'url' in media_item:
                                potential_url = media_item['url']
                                is_image = False
                                if media_item.get('type', '').startswith('image/'):
                                    is_image = True
                                elif media_item.get('medium') == 'image':
                                    is_image = True
                                elif potential_url and int(media_item['width']) > 400: # and any(potential_url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                                    is_image = True

                                if is_image and potential_url:
                                    image_url = potential_url
                                    print(f"      이미지 발견 (media_content): {image_url[:50]}...")
                                    break

                if image_url:
                    embed.set_image(url=image_url)
                    print(f"최종 선택된 이미지 URL: {image_url}")
                    pass
                else:
                    print("      이 항목에서 이미지를 찾지 못했습니다.")

                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published_dt = datetime.datetime(*entry.published_parsed[:6])
                        kst = datetime.timezone(datetime.timedelta(hours=9))
                        published_dt_kst = published_dt.replace(tzinfo=datetime.timezone.utc).astimezone(kst)
                        embed.timestamp = published_dt_kst
                    except Exception as e:
                        print(f"       발행 시각 변환 오류: {e}")
                        embed.timestamp = utils.utcnow()
                else:
                    embed.timestamp = utils.utcnow()

                feed_title = getattr(feed.feed, 'title', rss_feed_url)
                embed.set_footer(text=f"{feed_title}에서 불러온 정보다냥!")

                await channel.send(embed=embed)
                print("       >> Embed 형식으로 요약된 기사 정보를 채널에 성공적으로 전송했습니다.")

                await asyncio.sleep(1.5)

            except discord.Forbidden:
                print("  오류: 채널에 메시지(Embed)를 보낼 권한이 없습니다.")
            except discord.HTTPException as e:
                print(f"  오류: 채널 메시지(Embed) 전송 중 Discord API 오류: {e.status} - {e.text}")
                if e.status == 429:
                    retry_after = getattr(e, 'retry_after', 5.0)
                    print(f"  Discord Rate Limit 감지. {retry_after:.1f}초 대기 후 계속합니다.")
                    await asyncio.sleep(retry_after)
            except Exception as e:
                print(f"  오류: 메시지(Embed) 전송 중 예상치 못한 오류: {e}")

            if new_articles_processed_count % 15 == 0:
                 print(f"  15개 항목 처리 후 잠시 대기...")
                 await asyncio.sleep(60)

    print(f"채널 {channel_id_str}: 총 {new_articles_processed_count}개의 새 기사 처리 완료.")

    async with yaml_lock:
        try:
            if len(sent_articles) > max_keep:
                original_count = len(sent_articles)
                sent_articles = sent_articles[-max_keep:]
                print(f"채널 {channel_id_str}: 오래된 기사 링크 정리. {original_count} -> {len(sent_articles)}개 유지.")

            if os.path.exists(sent_articles_file):
                    with open(sent_articles_file, "r", encoding='utf-8') as f:
                        all_sent_data = yaml.safe_load(f) or {}
            else:
                 all_sent_data = {}

            all_sent_data[channel_id_str] = sent_articles

            with open(sent_articles_file, "w", encoding='utf-8') as f:
                yaml.dump(all_sent_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            print("sent_articles.yaml 파일 저장 완료")
        except Exception as e:
            print(f"sent_articles.yaml 파일 저장 중 오류 발생: {e}")


@client.event
async def on_ready():
    print(f"봇 로그인: {client.user.name} (ID: {client.user.id})")
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
        active_tasks = []
        for channel_id in DISCORD_CHANNEL_IDS:
            channel = client.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                print(f"  -> 채널 '{channel.name}' (ID: {channel.id}) 작업 생성 중...")
                task = asyncio.create_task(fetch_feed(channel, site_color_map), name=f"fetch_feed_{channel_id}")
                active_tasks.append(task)
            elif channel:
                 print(f"경고: 채널 ID {channel_id}는 텍스트 채널이 아닙니다: {type(channel)}")
            else:
                 print(f"경고: 채널 ID {channel_id}를 찾을 수 없거나 접근할 수 없습니다.")

        if active_tasks:
            results = await asyncio.gather(*active_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                 if isinstance(result, Exception):
                     task_name = active_tasks[i].get_name()
                     print(f"오류: 작업 '{task_name}' 실행 중 예외 발생: {type(result).__name__} - {result}")

            print(f"  -> 모든 채널 작업 완료 ({len(active_tasks)}개)")
        else:
            print("  -> 처리할 유효한 채널이 없습니다.")

        end_time = time.monotonic()
        print(f"{datetime.datetime.now()} - RSS 피드 확인 주기 완료 (총 소요 시간: {end_time - start_time:.2f}초)")
        wait_time = 600
        print(f"다음 확인까지 {wait_time // 60}분 대기...")
        await asyncio.sleep(wait_time)

if __name__ == "__main__":
    print("봇 시작 중...")
    try:
        client.run(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        print("오류: 잘못된 디스코드 봇 토큰입니다.")
    except discord.PrivilegedIntentsRequired:
        print("오류: Privileged Intents가 활성화되지 않았습니다.")
        print("Discord 개발자 포털에서 봇의 Privileged Gateway Intents (특히 Message Content Intent)를 확인/활성화하세요.")
    except Exception as e:
        print(f"봇 실행 중 심각한 오류 발생: {e}")
