import os
import sys
from bs4 import BeautifulSoup
import requests
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)
from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import datetime
import util.scrape_utils as SU
import logging

def _extract(url: str) -> str:
    response = requests.get(url, allow_redirects=True)
    soup = BeautifulSoup(response.content, 'html.parser')
    logging.getLogger(__name__).info(f"Scraped Content Page {url}")
    body = soup.find("main").children.__next__()
    # Decompose first child of body with class "wp-block-whitehouse-topper" and remove it.
    if body.find(class_="wp-block-whitehouse-topper"):
        body.find(class_="wp-block-whitehouse-topper").decompose()
    return str(body)

def _scrape_page(url, scrape_date: datetime.date):
    response = requests.get(url, allow_redirects=True)
    soup = BeautifulSoup(response.content, 'html.parser')
    logging.getLogger(__name__).info(f"Scraped {url}")
    # Look for H2 elements and get their parents.
    h2_elements = soup.find_all('h2')
    posts = [h2.parent for h2 in h2_elements if h2.parent.name == 'div']
    logging.getLogger(__name__).info(f"Found {len(posts)} posts on {url}")
    
    # For each post, look inside the H2 and extract the text and link.
    # Then, look for the sibling element of the H2. It will have two children, one is the article type and the second is the Date. Extract all four feilds.
    articles = []
    look_further = True
    for post in posts:
        h2 = post.find('h2')
        title = h2.text.strip()
        link = h2.find('a')['href']
        sibling = h2.find_next_sibling()
        article_type = sibling.find_all('div')[0].text.strip()
        date = sibling.find_all('div')[1].text.strip()
        # Process date to datetime.date. The format of the date is "Month Day, Year" (e.g., "October 10, 2023").
        date = datetime.datetime.strptime(date, '%B %d, %Y').date()
        # If the date is not the same as the input date, stop looking further.
        if date != scrape_date:
            look_further = False
            break
        # Print the extracted information
        # print(f"Title: {title}, Link: {link}, Article Type: {article_type}, Date: {date}")
        articles.append(ArticleLink(
            title=title, 
            link=link, 
            date=date, 
            tags=["White House", article_type], 
            process_posturing=True, 
            raw_content=_extract(link)
        ))
    res = LinkAggregationStep(articles=articles, look_further=look_further)       
    logging.getLogger(__name__).info(f"Processed {len(articles)} articles from {url}. Look Further: {look_further}")
    
    return res

def scrape(date: datetime.date):
    # Define the URL to scrape
    url_template = "https://www.whitehouse.gov/news/page/{{PAGE}}/"
    res = SU.iter_scrape(url_template, 1, date, _scrape_page)
    
    return res

if __name__ == "__main__":
    date = datetime.date(2025, 12, 12)
    res = scrape(date)
    print(res)
    