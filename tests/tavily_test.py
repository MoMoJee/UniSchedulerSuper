# To install: pip install tavily-python
from tavily import TavilyClient
client = TavilyClient("tvly-dev-xxx")
response = client.search(
    query="test",           # 仅此一项必填

    topic="general",        # None|"general"|"news"|"finance", using "general" is equal to use None
    search_depth=None,      # None|basic|advanced|fast|ultra-fast
                            # The depth of the search.advanced search is tailored to retrieve
                            # the most relevant sources and content snippets for your query,
                            # while basic search provides generic content snippets from each source

    time_range=None,        # None|"day"|"week"|"month"|"year"
    start_date=None,        # None|YYYY-MM-DD format
    end_date=None,          # None|YYYY-MM-DD format
    country="china",        # None|To use this parameter, must use general topic.
    include_domains=["www.example.com"],     # None|List(str) Only include results from these domains.
    exclude_domains=["www.blacklist.com"]    # None|List(str) Exclude results from these domains. Use"include_domains" to whitelist sources.
)
print(response)