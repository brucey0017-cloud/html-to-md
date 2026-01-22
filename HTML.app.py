import streamlit as st
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from readability import Document
import re
import time
import random
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import zipfile
import io

# --- 1. 页面与样式配置 ---
st.set_page_config(
    page_title="Web Clipper Ultimate | 全能采集专家", 
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. 核心工具函数 (经过严格规范检查) ---

def sanitize_filename(name):
    """
    清洗文件名，去除Windows/Mac/Linux文件系统不允许的字符
    并去除首尾空格
    """
    # 替换非法字符为空格
    clean_name = re.sub(r'[\\/*?:"<>|]', "", name)
    # 去除多余空格和换行
    clean_name = " ".join(clean_name.split())
    return clean_name[:50] # 限制长度防止文件名过长报错

def get_random_ua():
    ua_list = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
    return random.choice(ua_list)

def fetch_url(url, retries=3):
    attempt = 0
    while attempt < retries:
        try:
            time.sleep(random.uniform(0.5, 1.5))
            headers = {"User-Agent": get_random_ua(), "Referer": "https://www.google.com/"}
            response = requests.get(url, headers=headers, timeout=15)
            
            # 编码防御性处理
            if response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding if response.apparent_encoding else 'utf-8'
            
            if response.status_code == 403: return "ERROR: 403 Forbidden (反爬拦截)"
            if response.status_code == 404: return "ERROR: 404 Not Found"
            
            response.raise_for_status()
            return response.text
        except Exception as e:
            attempt += 1
            if attempt == retries: return f"ERROR: {str(e)}"
            time.sleep(1)

def parse_sitemap(sitemap_url):
    try:
        xml_content = fetch_url(sitemap_url)
        if xml_content.startswith("ERROR"): return None, xml_content
        root = ET.fromstring(xml_content)
        namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = []
        for url_tag in root.findall('.//ns:loc', namespace): urls.append(url_tag.text)
        if not urls:
            for url_tag in root.findall('.//loc'): urls.append(url_tag.text)
        return urls, None
    except Exception as e:
        return None, f"Sitemap 解析异常: {str(e)}"

def clean_html_content(soup, base_url):
    for tag in soup(['script', 'style', 'iframe', 'noscript', 'header', 'footer', 'nav']): tag.decompose()
    for img in soup.find_all('img'):
        if img.get('src') and not img['src'].startswith('http'):
            if img['src'].startswith('//'): img['src'] = 'https:' + img['src']
            elif img['src'].startswith('/'): 
                domain = '/'.join(base_url.split('/')[:3])
                img['src'] = domain + img['src']
    return soup

def process_single_article(url):
    """核心处理逻辑"""
    try:
        html_content = fetch_url(url)
        if not html_content or html_content.startswith("ERROR:"): return None, url, html_content

        if "mp.weixin.qq.com" in url:
            soup = BeautifulSoup(html_content, 'html.parser')
            meta_title = soup.find('meta', property='og:title')
            title = meta_title['content'] if meta_title else soup.title.string.strip()
            content_div = soup.find('div', id='js_content')
            if content_div:
                for img in content_div.find_all('img'):
                    if 'data-src' in img.attrs: img['src'] = img['data-src']
                final_html = str(content_div)
            else: return None, url, "公众号内容解析失败"
        else:
            doc = Document(html_content)
            title = doc.title()
            soup = BeautifulSoup(doc.summary(), 'html.parser')
            soup = clean_html_content(soup, url)
            for sidebar in soup.find_all(class_=re.compile("sidebar|toc|nav")): sidebar.decompose()
            final_html = str(soup)

        markdown_text = md(final_html, heading_style="ATX")
        title = sanitize_filename(title)
        
        # 返回: (清洗后的标题, 原链接, Markdown内容)
        full_content = f"# {title}\n\n> Source: {url}\n\n{markdown_text}\n\n---\n\n"
        return title, url, full_content

    except Exception as e:
        return None, url, f"Processing Error: {str(e)}"

# --- 3. 侧边栏与配置 ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2083/2083236.png", width=50)
    st.header("⚙️ 控制台")
    
    input_mode = st.radio(
        "1. 采集来源:", 
        ("📝 批量链接列表", "🗺️ 站点地图 (Sitemap)"),
        help="Sitemap 适合一次性抓取整个文档库"
    )
    
    st.divider()
    
    # --- 新增功能：下载格式选择 ---
    output_format = st.radio(
        "2. 下载格式:",
        ("📑 合并为一个 Markdown", "📦 分文件打包 (ZIP)"),
        captions=["所有文章在一个长文档里", "每篇文章一个单独的 .md 文件"],
        index=0
    )
    
    st.divider()
    st.caption("Web Clipper Ultimate v3.0")

# --- 4. 主界面逻辑 ---
st.title("💎 Web Clipper Ultimate")

input_placeholder = "https://mp.weixin.qq.com/s/...\nhttps://example.com/article..." if "列表" in input_mode else "https://example.com/sitemap.xml"
input_label = "🔗 在此粘贴链接 (每行一个)" if "列表" in input_mode else "🗺️ 在此粘贴 Sitemap.xml 链接"

with st.form("main_form"):
    urls_input = st.text_area(input_label, height=200, placeholder=input_placeholder)
    submitted = st.form_submit_button("⚡ 开始采集", type="primary")

if submitted and urls_input:
    target_urls = []
    
    # 1. 解析 URL
    if "Sitemap" in input_mode:
        with st.spinner("🔍 正在扫描站点地图..."):
            parsed_urls, error = parse_sitemap(urls_input.strip())
            if error: st.error(error)
            else: target_urls = parsed_urls
    else:
        target_urls = [line.strip() for line in urls_input.split('\n') if line.strip().startswith('http')]

    # 2. 执行采集
    if target_urls:
        success_results = [] # 存储 (title, url, content)
        fail_logs = []       # 存储 (url, reason)
        
        st.info(f"🚀 任务已启动，共 {len(target_urls)} 个目标。格式: {output_format}")
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 动态调整线程数
        workers = 4 if len(target_urls) < 50 else 3
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_url = {executor.submit(process_single_article, url): url for url in target_urls}
            completed = 0
            
            for future in as_completed(future_to_url):
                title, url, content = future.result()
                completed += 1
                progress_bar.progress(completed / len(target_urls))
                status_text.text(f"Processing ({completed}/{len(target_urls)}): {title if title else '解析中...'}")
                
                if title:
                    success_results.append((title, url, content))
                else:
                    fail_logs.append(f"{url} | 原因: {content}")

        progress_bar.empty()
        status_text.empty()
        
        # 3. 结果统计
        col1, col2 = st.columns(2)
        col1.metric("✅ 成功", len(success_results))
        col2.metric("⚠️ 失败", len(fail_logs), delta_color="inverse")
        
        if fail_logs:
            with st.expander("查看失败日志"):
                st.text("\n".join(fail_logs))

        # 4. 生成下载文件 (关键分支逻辑)
        timestamp = int(time.time())
        
        # === 模式 A: 合并下载 ===
        if "合并" in output_format:
            full_doc = f"# Export Collection\nDate: {time.strftime('%Y-%m-%d')}\n\n---\n\n"
            if fail_logs:
                full_doc += "## ⚠️ Failed URLs\n" + "\n".join(fail_logs) + "\n\n---\n\n"
            
            for _, _, content in success_results:
                full_doc += content
                
            st.download_button(
                label="📥 下载合并文档 (.md)",
                data=full_doc.encode('utf-8-sig'), # 强制 BOM 修复乱码
                file_name=f"merged_export_{timestamp}.md",
                mime="text/markdown",
                type="primary"
            )

        # === 模式 B: ZIP 打包下载 ===
        else:
            # 在内存中创建 ZIP
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                # 写入成功的文件
                for idx, (title, _, content) in enumerate(success_results):
                    # 文件名格式: 01_标题.md (防止重名覆盖)
                    file_name = f"{str(idx+1).zfill(3)}_{title}.md"
                    # 写入 ZIP 时强制 utf-8-sig 编码内容
                    zip_file.writestr(file_name, content.encode('utf-8-sig'))
                
                # 写入失败日志 (如果有)
                if fail_logs:
                    error_log = "Failed URLs:\n" + "\n".join(fail_logs)
                    zip_file.writestr("_失败日志_errors.txt", error_log.encode('utf-8-sig'))
            
            st.download_button(
                label="📦 下载压缩包 (.zip)",
                data=zip_buffer.getvalue(),
                file_name=f"batch_export_{timestamp}.zip",
                mime="application/zip",
                type="primary"
            )
            
    else:
        st.warning("⚠️ 未检测到有效链接，请检查输入。")
