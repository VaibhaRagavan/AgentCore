from mcp.server.fastmcp import FastMCP
from langchain_tavily import TavilySearch
import os,requests,feedparser,wikipedia
from dotenv import load_dotenv
from datetime import datetime, timedelta
import socket
load_dotenv()
socket.setdefaulttimeout(10)

General_queries={
       # general
    "latest", "recent", "update", "updates", "today", "top news",
    "headlines", "what's happening", "whats happening",
    "trending", "breaking", "what happened", "any news",
    "today news", "news today", "current", "anything new",
    # sport specific
    "latest scores", "recent matches", "fixtures", "results",
    "standings", "top sports", "sports today", "sports news",
    "latest sports", "recent sports", "any matches", "live scores",
    # business specific
    "market update", "stock update", "market news", "business today",
    "latest business", "financial news", "economy update", "markets today",
    "business news", "latest market", "any business news",
    }
server=FastMCP("server",stateless_http=True,host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000))
)

##SearchTool 
@server.tool()
def tavily_search(query:str)->str:
    """Use this tool to search anything from internet like google serach.
     Fact-check or verify a specific claim using live web search. 
     Use this AFTER retrieving news from RSS tools to confirm accuracy."""
    search = TavilySearch(max_results=5)
    results=search.run(query)
    return str(results)

##Wikipedia tool
@server.tool()
def wiki_search(query:str)->str:
    "Search query on wikipedia and return the summary"
    search=wikipedia.search(query)
    if not search:
        return "No results found"
    try:
        page=wikipedia.page(search[0],auto_suggest=False)
        return str(page.summary)
    except wikipedia.exceptions.DisambiguationError as e:
        page=wikipedia.page(e.options[0], auto_suggest=False)
        return f"{page.summary}\n\nSource:{page.url}"
    except wikipedia.exceptions.PageError:
        return "No Pages found" 
    except Exception as e:
        return f"Wikipedia search failed: {str(e)}"
##Weather tool
@server.tool()
def weather(city:str)->str:
    "Get Weather for the city"
    api_key=os.getenv("WEATHER_API_KEY")
    if not api_key:
        raise ValueError("NO apikey found in the environment")
    params=({
        "q":city,
        "appid":api_key,
        "units":"metric"
    })
    search=requests.get("http://api.openweathermap.org/data/2.5/weather",params=params)
    data=search.json()
    if data.get("cod") != 200:
        return "City not found"
    return str(data)

##News api for older news
@server.tool()
def get_old_news(query:str,days_ago:int)->str:
    "Get old news from past using newsapi.org"
    api_key=os.getenv("NEWS_API_KEY")
    if not api_key:
        raise ValueError("NO apikey found in the environment")
    params={
        "q":query,
        "from":(datetime.now()-timedelta(days=days_ago)).strftime("%Y-%m-%d"),
        "to":datetime.now().strftime("%Y-%m-%d"),
        "sortBy":"publishedAt",
        "apiKey":api_key,
        "language":"en"
    }
    search=requests.get("https://newsapi.org/v2/everything",params=params)

    data=search.json()
    results=[]
    if data.get("status")!= "ok" or not data.get("articles"):
        return "No news found for the query"
    for news in data["articles"][:5]:
        results.append({
            "title":news["title"],
            "description":news["description"],
            "url":news["url"]
        })
    return str(results[:3])
##deduplication function to avoid dulpication
def dedup(items):
    seen=[]
    unique=[]
    for item in items:
        title= item.get("title", "").lower()
        is_dup=False

        for s in seen:
            overlap=len(set(title.split()) & set(s.split()))
            if overlap >3:
                is_dup=True
                break
        if not is_dup:
            seen.append(title)
            unique.append(item)
    return unique
##general quries
def is_generic(query:str)->bool:
    q=query.lower().strip()
    if len(q.split())>4:
        return False
    return any(word in q for word in General_queries)

##news for genral queries
def general_news(rss_feeds:dict)->str:
    "Fetching the news for the general quires without scoring."
    results=[]
    for name,url in rss_feeds.items():
        try:
            feed =feedparser.parse(url)
            for entry in feed.entries[:3]:
                results.append({
                "title":entry.title,
                "description":entry.get("summary", "No summary available"),
                "link":entry.link,
                "source":name
            })
        except Exception as e:
            print(f"{name} failed with error: {e}")
            continue
    result=dedup(results)
    if result:
        return str(result[:5])
    else:
        return "No news found for the query"
    
##news fetch function
def fetch_news(rss_feeds:dict,query:str)->list:
    "Fetching news for quires using scoring"
    q=query.lower()
    results=[]
    for name,url in rss_feeds.items():
        try:
            feed=feedparser.parse(url)
            for entry in feed.entries[:15]:
                title=entry.title.lower()
                summary=entry.get("summary", "").lower()
                text=title+" "+summary

                score=0
                #match keywords
                query_words=[w for w in q.split() if len(w)>3]

                if q in title:
                    score +=4
                elif q in text:
                    score +=3
                for words in query_words:
                    if words in title:
                        score +=2
                    elif words in text:
                        score +=1
                if score >0:
                    results.append({
                    "title":entry.title,
                    "description":entry.get("summary", "No summary available"),
                    "link":entry.link,
                    "source":name,
                    "score":score
                })
        except Exception as e:
            print(f"{name} failed with error: {e}")
            continue
        
    return results

##Sports news
@server.tool()
def sports_news(query:str)->str:
    """Get sports news. Use for queries about football, cricket, tennis, F1, 
    basketball, rugby, golf, Olympics, match results, fixtures, standings, 
    player transfers or any sport related topic."""
    if not query:
         raise ValueError("Query cannot be empty")
    rss_feeds={
        "bbc_sport":"http://feeds.bbci.co.uk/sport/rss.xml",
        "epsn_sport":"https://www.espn.com/espn/rss/news",
        "sky_sport":"https://www.skysports.com/rss/12040",
        "epsn_cric":"https://www.espncricinfo.com/rss/content/story/feeds/0.xml",
        "f1_sport":"https://www.motorsport.com/rss/f1/news/"
    }
    if is_generic(query):
        return general_news(rss_feeds)
    
    out=fetch_news(rss_feeds, query)
    results=sorted(out, key=lambda x:x["score"], reverse=True)
    result=dedup(results)
    if result:
        return str(result[:5])
    else:
        #fallback if when rss finds nothing
        search=tavily_search(query)
        return str(search)
##Asia news
@server.tool()
def get_asian_news(query:str)->str:
    """Get news from Asia. Use for queries about India, China, Japan, South Korea, 
    North Korea, Pakistan, Bangladesh, Sri Lanka, Southeast Asia, Taiwan, 
    Hong Kong, or any Asian country or region."""
    if not query:
         raise ValueError("Query cannot be empty")
    rss_feeds={
        "the_hindu":"https://www.thehindu.com/feeder/default/rss",
        "scmp":"https://www.scmp.com/rss/91/feed",
        "japan_times":"https://www.japantimes.co.jp/feed/topstories/",
        "nikkei_asia":"https://asia.nikkei.com/rss/feed/nar",
        "times_of_india_world":"https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",
        "hindustan_times":"https://www.hindustantimes.com/feeds/rss/world-news/rssfeed.xml",
    }
    if is_generic(query):
        return general_news(rss_feeds)
    out=fetch_news(rss_feeds, query)
    results=sorted(out, key=lambda x:x["score"], reverse=True)
    result=dedup(results)
    if result:
        return str(result[:5])
    else:
        #fallback if when rss finds nothing
        search=tavily_search(query)
        return str(search)

##Middle East news
@server.tool()
def get_middleeast_news(query:str)->str:
    """Get news from the Middle East. Use for queries about Israel, Palestine, 
    Iran, Iraq, Saudi Arabia, Syria, Lebanon, Jordan, UAE, Yemen, Gaza,
    or any Middle Eastern country or conflict."""
    if not query:
         raise ValueError("Query cannot be empty")
    rss_feeds={
        "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
        "times_of_israel": "https://www.timesofisrael.com/feed/",
        "egypt_independent": "https://egyptindependent.com/feed/",
    "middle_east_eye": "https://www.middleeasteye.net/rss",}
    
    if is_generic(query):
        return general_news(rss_feeds)
    
    out=fetch_news(rss_feeds, query)
    results=sorted(out, key=lambda x:x["score"], reverse=True)
    result=dedup(results)
    if result:
        return str(result[:5])
    else:
        #fallback if when rss finds nothing
        search=tavily_search(query)
        return str(search)
##Africa news
@server.tool()
def get_africa_news(query:str)->str:
    """Get news from Africa. Use for queries about Nigeria, South Africa, Kenya, 
    Tanzania, Ghana, Ethiopia, Egypt, Sudan, or any African country or region."""
    if not query:
        raise ValueError("Query cannot be empty")
    rss_feeds={
        "all_africa": "https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf",
        "news24_za":      "https://feeds.news24.com/articles/news24/TopStories/rss",
        "mail_guardian":  "https://mg.co.za/feed/",
        "premium_times":  "https://www.premiumtimesng.com/feed",
    }
         
    if is_generic(query):
        return general_news(rss_feeds)
    
    out=fetch_news(rss_feeds,query)
    results=sorted(out, key=lambda x:x["score"], reverse=True)
    result=dedup(results)
    if result:
        return str(result[:5])
    else:
        #fallback if when rss finds nothing
        search=tavily_search(query)
        return str(search)
##Europe news
@server.tool()
def get_europe_news(query:str)->str:
    """Get news from Europe. Use for queries about UK, France, Germany, Ireland, 
    Spain, Italy, Ukraine, Russia, NATO, EU, European politics or any European 
    country or region."""
    if not query:
        raise ValueError("Query cannot be empty")
    rss_feeds={
        "rte": "https://www.rte.ie/feeds/rss/?index=/news",
        "bbc": "https://feeds.bbci.co.uk/news/rss.xml",
        "dw": "https://rss.dw.com/rdf/rss-en-all",
        "le_monde": "https://www.lemonde.fr/en/rss/une.xml",
        "france24": "https://www.france24.com/en/rss",
        "el_pais": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
    }
    if is_generic(query):
        return general_news(rss_feeds)
    
    out=fetch_news(rss_feeds, query)
    results=sorted(out, key=lambda x:x["score"], reverse=True)
    result=dedup(results)
    if result:
        return str(result[:5])
    else:
        #fallback if when rss finds nothing
        search=tavily_search(query)
        return str(search)
##American news
@server.tool()
def get_american_news(query:str)->str:
    """Get news from the Americas. Use for queries about USA, US politics, Canada, 
    Mexico, Brazil, Latin America, Trump, Congress, White House or any American 
    country or topic."""
    if not query:
        raise ValueError("Query cannot be empty")
    rss_feeds={
                "guardian": "https://www.theguardian.com/world/rss",
        "nyt_world": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "washington_post_world": "https://feeds.washingtonpost.com/rss/world",
         "npr_world":      "https://feeds.npr.org/1004/rss.xml",
    }
    if is_generic(query):
        return general_news(rss_feeds)
    
    out=fetch_news(rss_feeds,query)
    results= sorted(out,key=lambda x: x["score"], reverse=True)
    result=dedup(results)
    if not result:
        #fallback if when rss finds nothing
        search=tavily_search(query)
        return str(search)
    return str(result[:5])

##Global news
@server.tool()
def get_global_news(query:str)->str:
    """Get global/worldwide news. Use when no specific region is mentioned or for 
    general queries like top news, latest headlines, breaking news, trending stories, 
    or what is happening in the world today."""
    if not query:
        raise ValueError("Query cannot be empty")
    rss_feeds={
        "rte": "https://www.rte.ie/feeds/rss/?index=/news",
        "bbc": "https://feeds.bbci.co.uk/news/rss.xml",
        "guardian": "https://www.theguardian.com/world/rss",
        "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
        "the_hindu":"https://www.thehindu.com/feeder/default/rss",
        "scmp":"https://www.scmp.com/rss/91/feed",
        "japan_times":"https://www.japantimes.co.jp/feed/topstories/",
    }
    if is_generic(query):
        return general_news(rss_feeds)
    
    out=fetch_news(rss_feeds, query)
    results= sorted(out,key=lambda x: x["score"], reverse=True)
    result=dedup(results)
    if not result:
        #fallback if when rss finds nothing
        search=tavily_search(query)
        return str(search)
    return str(result[:5])

##Bussiness news
@server.tool()
def get_bussiness_news(query:str)->str:
    """Get business and financial news. Use for queries about stocks, markets, 
    economy, inflation, GDP, companies, earnings, cryptocurrency, oil prices, 
    trade, investments or any financial or business topic."""
    if not query:
        raise ValueError("Query cannot be empty")
    rss_feeds={
        "ft": "https://www.ft.com/?format=rss",
        "bloomberg": "https://feeds.bloomberg.com/markets/news.rss",
        "forbes": "https://www.forbes.com/business/feed/",
        "market_watch":   "https://feeds.marketwatch.com/marketwatch/topstories/",
    "investing_com":  "https://www.investing.com/rss/news.rss",
    "yahoo_finance":  "https://finance.yahoo.com/news/rssindex",
          
}
    if is_generic(query):
        return general_news(rss_feeds)
    
    out=fetch_news(rss_feeds,query)
    results=sorted(out, key=lambda x:x["score"], reverse=True)
    result=dedup(results)
    if result:
        return str(result[:5])
    else:
        #fallback if when rss finds nothing
        search=tavily_search(query)
        return str(search)
   


if __name__ == "__main__":
    server.run(transport="streamable-http")

    




