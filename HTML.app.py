import streamlit as st
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from readability import Document
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 页面设置 ---
st.set_page_config(
    page_title="全能网页批量转Markdown (防乱码版)", 
    page_icon="🛡️",
    layout="wide"
)

st.title("🛡️ 全能网页批量抓取工具 (修复乱码版)")
st.markdown("已修复 Windows 下打开文件显示乱码的问题，并增强了对公众号的编码识别。")

# --- 核心配置 ---
MAX_WORKERS = 4
MAX_RETRIES = 3

# --- 辅助函数 ---
def get_random_ua():
    ua_list = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
    return random.choice(ua_list)

def fetch_url(url, retries=MAX_RETRIES):
    attempt = 0
    while attempt < retries:
        try:
            time.sleep(random.uniform(0.5, 1.5))
            headers = {
                "User-Agent": get_random_ua(),
                "Referer": "https://www.google.com/"
            }
            response = requests.get(url, headers=headers, timeout=15)
            
            # 【关键修复1】强制修正编码，防止抓取时就乱码
            # 优先使用 apparent_encoding，如果识别失败则回退到 utf-8
            if response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding if response.apparent_encoding else 'utf-8'
            
            # 针对部分特殊网页的手动修正
            if "charset=gbk" in response.text.lower():
                response.encoding = 'gbk'
                
            if response.status_code == 403:
                return "ERROR: 403 Forbidden"
            if response.status_code == 404:
                return "ERROR: 404 Not Found"
            
            response.raise_for_status()
            return response.text
        except Exception as e:
            attempt += 1
            if attempt == retries:
                return f"ERROR: {str(e)}"
            time.sleep(1)

def clean_html_content(soup, base_url):
    for tag in soup(['script', 'style', 'iframe', 'noscript', 'header', 'footer', 'nav']):
        tag.decompose()
    for img in soup.find_all('img'):
        if img.get('src') and not img['src'].startswith('http'):
            if img['src'].startswith('//'):
                img['src'] = 'https:' + img['src']
            elif img['src'].startswith('/'):
                domain = '/'.join(base_url.split('/')[:3])
                img['src'] = domain + img['src']
    return soup

def process_single_article(url):
    try:
        html_content = fetch_url(url)
        if html_content.startswith("ERROR:"):
            return None, url, html_content

        if "mp.weixin.qq.com" in url:
            soup = BeautifulSoup(html_content, 'html.parser')
            # 兼容不同公众号模板的标题获取
            meta_title = soup.find('meta', property='og:title')
            title = meta_title['content'] if meta_title else soup.title.string.strip()
            content_div = soup.find('div', id='js_content')
            if content_div:
                for img in content_div.find_all('img'):
                    if 'data-src' in img.attrs:
                        img['src'] = img['data-src']
                final_html = str(content_div)
            else:
                return None, url, "未找到公众号正文"
        else:
            doc = Document(html_content)
            title = doc.title()
            soup = BeautifulSoup(doc.summary(), 'html.parser')
            soup = clean_html_content(soup, url)
            final_html = str(soup)

        markdown_text = md(final_html, heading_style="ATX")
        title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
        
        final_block = f"# {title}\n\n> 来源: {url}\n\n{markdown_text}\n\n---\n\n"
        return title, url, final_block

    except Exception as e:
        return None, url, f"处理异常: {str(e)}"

# --- 界面 ---
with st.form("main_form"):
    urls_input = st.text_area("📝 粘贴链接 (每行一个):", height=300)
    submitted = st.form_submit_button("🚀 开始抓取 (修复乱码版)")

if submitted and urls_input:
    url_list = [line.strip() for line in urls_input.split('\n') if line.strip().startswith('http')]
    
    if not url_list:
        st.error("没有有效链接")
    else:
        results = []
        errors = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {executor.submit(process_single_article, url): url for url in url_list}
            completed = 0
            
            for future in as_completed(future_to_url):
                title, original_url, content = future.result()
                completed += 1
                progress_bar.progress(completed / len(url_list))
                status_text.text(f"处理中: {completed}/{len(url_list)}")
                
                if title:
                    results.append(content)
                else:
                    errors.append(f"- [失败] {original_url} : {content}")

        # --- 结果处理 ---
        full_document = f"# 抓取合集\n生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n"
        if errors:
            full_document += "## ⚠️ 失败列表\n" + "\n".join(errors) + "\n\n---\n\n"
        full_document += "".join(results)
        
        st.success(f"✅ 处理完成！")
        
        # 【关键修复2】在这里！添加 utf-8-sig 编码
        # .encode('utf-8-sig') 会给文件加上 BOM 头，让 Windows 识别为 UTF-8
        st.download_button(
            label="📥 下载 Markdown (已修复乱码)",
            data=full_document.encode('utf-8-sig'), 
            file_name=f"articles_fixed_{int(time.time())}.md",
            mime="text/markdown",
            type="primary"
        )
