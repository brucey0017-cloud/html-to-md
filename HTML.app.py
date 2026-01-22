import streamlit as st
import requests
from bs4 import BeautifulSoup
import trafilatura
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
import zipfile
import io

# --- 1. 页面配置与审美优化 ---
st.set_page_config(
    page_title="Magic Clipper | 智能网页剪藏",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 注入自定义 CSS 提升审美
st.markdown("""
    <style>
        .reportview-container { margin-top: -2em; }
        .stDeployButton {display:none;}
        header {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        .stTextArea textarea {
            font-family: "SF Mono", "Roboto Mono", monospace;
            font-size: 14px;
            color: #333;
        }
    </style>
""", unsafe_allow_html=True)

# --- 2. 核心工具函数 ---

def get_headers():
    """生成高度伪装的请求头，解决 Medium 等网站的 403 问题"""
    ua_list = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ]
    return {
        "User-Agent": random.choice(ua_list),
        "Referer": "https://www.google.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    }

def fetch_url(url, retries=3):
    """通用的网页下载器"""
    attempt = 0
    while attempt < retries:
        try:
            time.sleep(random.uniform(0.5, 1.5)) # 增加一点延迟，防封
            response = requests.get(url, headers=get_headers(), timeout=20)
            
            if response.status_code == 404:
                return None
            
            response.raise_for_status()
            
            # 处理编码
            if response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding
            
            return response.text
        except Exception as e:
            attempt += 1
            if attempt == retries:
                # 记录最后一次报错
                print(f"Error fetching {url}: {e}")
                return None
    return None

def clean_filename(title):
    if not title: return "Untitled_Document"
    clean = re.sub(r'[\\/*?:"<>|]', "", title)
    clean = " ".join(clean.split())
    return clean[:80]

# --- 3. 智能解析引擎 (含 Sitemap 支持) ---

def parse_sitemap(url):
    """解析 Sitemap.xml 提取链接"""
    xml_content = fetch_url(url)
    if not xml_content:
        return []
    
    try:
        soup = BeautifulSoup(xml_content, 'xml') # 使用 xml 解析器
        urls = []
        # 兼容标准 sitemap 格式
        for loc in soup.find_all('loc'):
            if loc.text.strip():
                urls.append(loc.text.strip())
        return urls
    except Exception:
        return []

def parse_wechat(html, url):
    """【专用通道】微信公众号"""
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.find('meta', property='og:title')
    title = title['content'] if title else soup.title.string.strip()
    
    content_div = soup.find('div', id='js_content')
    if not content_div:
        return title, "Error: 无法找到公众号正文，可能是链接已失效。"
    
    for img in content_div.find_all('img'):
        if 'data-src' in img.attrs:
            img['src'] = img['data-src']
            del img['data-src']
    
    html_str = str(content_div)
    markdown = trafilatura.extract(html_str, include_images=True, output_format='markdown')
    return title, markdown

def parse_general(html, url):
    """【通用通道】GitBook / Substack / Medium"""
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.string.strip() if soup.title else "Unknown_Title"
    
    # === GitBook 强力补丁 ===
    # 如果 URL 包含 gitbook 或 docs 关键词，且 trafilatura 可能失败，尝试强制提取
    is_gitbook = "gitbook" in url or "docs" in url
    
    # 策略 1: 优先使用 trafilatura 智能提取
    markdown = trafilatura.extract(html, include_images=True, include_formatting=True, output_format='markdown')
    
    # 策略 2: 如果是 GitBook 且内容太少（可能只抓到了菜单），尝试手动提取 .markdown-section
    if is_gitbook and (not markdown or len(markdown) < 200):
        # GitBook 通常把正文放在 markdown-section 类里
        main_content = soup.find(class_="markdown-section")
        if not main_content:
            # 或者尝试 main 标签
            main_content = soup.find("main")
            
        if main_content:
            # 清理干扰元素
            for junk in main_content.find_all(["script", "style", "nav"]):
                junk.decompose()
            # 再次转换
            markdown = trafilatura.extract(str(main_content), include_images=True, output_format='markdown')

    if not markdown:
        return title, None
        
    return title, markdown

def process_single_url(url):
    url = url.strip()
    if not url.startswith('http'): return None, url, "Invalid URL"
    
    # 这一步下载耗时较长
    html = fetch_url(url)
    
    if not html:
        # 针对 Medium 403 做特殊提示
        if "medium.com" in url:
            return None, url, "Error: Medium 反爬拦截 (403)，请尝试使用 VPN 或稍后再试。"
        return None, url, "Network Error: 无法访问链接"

    try:
        if "mp.weixin.qq.com" in url:
            title, content = parse_wechat(html, url)
        else:
            title, content = parse_general(html, url)
            
        if not content:
            return title, url, "Content Empty: 无法提取正文 (可能是纯动态页面)"
            
        full_doc = f"# {title}\n\n> 来源: {url}\n> 时间: {time.strftime('%Y-%m-%d')}\n\n---\n\n{content}\n\n"
        return clean_filename(title), url, full_doc
        
    except Exception as e:
        return None, url, f"System Error: {str(e)}"

# --- 4. UI 界面逻辑 ---

st.title("🔮 Magic Clipper v3.1")
st.caption("支持：微信公众号 / GitBook (含 Sitemap) / Substack / Medium / 知乎 等")

with st.expander("⚙️ 设置", expanded=False):
    st.info("💡 提示：支持粘贴 Sitemap.xml 链接，系统会自动抓取其中所有页面。")
    # 调整顺序：合并下载在第一个 (默认)
    output_mode = st.radio("下载偏好:", ["📑 合并为一个 Markdown", "📦 分文件打包 (ZIP)"], index=0, horizontal=True)

urls_input = st.text_area("🔗 在此粘贴链接 或 Sitemap.xml (一行一个)", height=150, placeholder="https://docs.slerf.tools/sitemap-pages.xml\nhttps://mp.weixin.qq.com/s/...")

if st.button("🚀 开始采集", type="primary"):
    if not urls_input.strip():
        st.warning("⚠️ 请先输入链接")
    else:
        raw_lines = [line.strip() for line in urls_input.split('\n') if line.strip().startswith('http')]
        
        # === 1. 预处理：Sitemap 裂变 ===
        target_urls = []
        with st.status("🔍 正在分析链接...", expanded=True) as status:
            for url in raw_lines:
                if url.endswith('.xml'):
                    status.write(f"正在解析 Sitemap: {url}")
                    sub_urls = parse_sitemap(url)
                    if sub_urls:
                        status.write(f"✅ 成功从 Sitemap 提取出 {len(sub_urls)} 个链接")
                        target_urls.extend(sub_urls)
                    else:
                        status.write(f"⚠️ Sitemap 解析失败或为空: {url}")
                else:
                    target_urls.append(url)
            
            # 去重
            target_urls = list(dict.fromkeys(target_urls))
            
            if not target_urls:
                status.update(label="❌ 未找到有效文章链接", state="error")
                st.stop()
            
            status.update(label=f"✅ 链接分析完成，准备抓取 {len(target_urls)} 个页面", state="complete", expanded=False)

        # === 2. 并发采集 ===
        success_data = []
        fail_log = []
        
        progress_bar = st.progress(0)
        status_box = st.status(f"🚀 正在极速抓取 ({len(target_urls)} 篇)...", expanded=True)
        
        # GitBook 这种站点最好不要并发太高，容易被封，设置为 4
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_url = {executor.submit(process_single_url, url): url for url in target_urls}
            
            completed = 0
            for future in as_completed(future_to_url):
                title, url, content = future.result()
                completed += 1
                progress_bar.progress(completed / len(target_urls))
                
                if content and not content.startswith(("Error", "Network", "Content", "System")):
                    success_data.append((title, content))
                    status_box.write(f"✅ {title[:30]}...")
                else:
                    err = content if content else "Unknown"
                    fail_log.append(f"{url} -> {err}")
                    status_box.write(f"❌ 失败: {url} ({err})")
        
        status_box.update(label="✨ 任务完成!", state="complete", expanded=False)
        
        # === 3. 结果交付 ===
        st.divider()
        col1, col2 = st.columns(2)
        col1.metric("成功", len(success_data))
        col2.metric("失败", len(fail_log), delta_color="inverse")
        
        if fail_log:
            with st.expander("查看失败详情"):
                st.text("\n".join(fail_log))

        if success_data:
            timestamp = int(time.time())
            
            # 模式 A: 合并 (默认)
            if "合并" in output_mode:
                merged_content = f"# Magic Clipper Export\nExport Time: {time.strftime('%Y-%m-%d %H:%M')}\n\n---\n\n"
                # 添加目录 (可选，为了更好看)
                merged_content += "## 目录\n"
                for i, (fname, _) in enumerate(success_data):
                    merged_content += f"{i+1}. {fname}\n"
                merged_content += "\n---\n\n"
                
                for fname, text in success_data:
                    merged_content += f"{text}\n\n"
                
                st.download_button(
                    label="📥 下载合并文档 (.md)",
                    data=merged_content.encode('utf-8'),
                    file_name=f"merged_export_{timestamp}.md",
                    mime="text/markdown",
                    type="primary"
                )
            
            # 模式 B: ZIP
            else:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zf:
                    for idx, (fname, text) in enumerate(success_data):
                        safe_name = f"{str(idx+1).zfill(3)}_{fname}.md"
                        zf.writestr(safe_name, text.encode('utf-8'))
                    if fail_log:
                        zf.writestr("_FAIL_LOG.txt", "\n".join(fail_log).encode('utf-8'))
                        
                st.download_button(
                    label="📦 下载 ZIP 压缩包",
                    data=zip_buffer.getvalue(),
                    file_name=f"batch_export_{timestamp}.zip",
                    mime="application/zip",
                    type="primary"
                )
