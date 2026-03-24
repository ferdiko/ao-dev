"""
CrewAI Multi-Tool Example

This example demonstrates using multiple external tools in a CrewAI workflow:
- BraveSearchTool: Web search via Brave Search API
- SerperScrapeWebsiteTool: Website scraping via Serper API

Required API keys (set as environment variables):
- BRAVE_API_KEY: Get from https://brave.com/search/api/
- SERPER_API_KEY: Get from https://serper.dev/
- ANTHROPIC_API_KEY: For the LLM

To run:
    export BRAVE_API_KEY=your_brave_api_key
    export SERPER_API_KEY=your_serper_api_key
    export ANTHROPIC_API_KEY=your_anthropic_api_key
    so-record example_workflows/debug_examples/crewai_multi_tool.py
"""

from crewai import Agent, Task, Crew, Process, LLM
from crewai_tools import BraveSearchTool, SerperScrapeWebsiteTool


def main():
    # Use a fast, cheap Anthropic model
    llm = LLM(
        model="claude-sonnet-4-5",
        max_tokens=1024,
    )

    # Initialize tools
    brave_search = BraveSearchTool()
    serper_scrape = SerperScrapeWebsiteTool()

    # Agent 1: Researcher - uses Brave Search to find relevant sources
    researcher = Agent(
        role="Research Analyst",
        goal="Find the most relevant and authoritative sources on a topic",
        backstory=(
            "You are an expert research analyst who excels at finding "
            "high-quality information sources using web search. You identify "
            "the most credible and relevant URLs for further analysis."
        ),
        tools=[brave_search],
        llm=llm,
        verbose=True,
    )

    # Agent 2: Content Extractor - uses Serper Scrape to extract content
    extractor = Agent(
        role="Content Extractor",
        goal="Extract and summarize key information from web pages",
        backstory=(
            "You are skilled at extracting meaningful content from websites. "
            "You can scrape web pages and distill the most important information "
            "into clear, structured summaries."
        ),
        tools=[serper_scrape],
        llm=llm,
        verbose=True,
    )

    # Agent 3: Synthesizer - combines findings into a report
    synthesizer = Agent(
        role="Report Synthesizer",
        goal="Create comprehensive summaries from multiple sources",
        backstory=(
            "You are an expert at synthesizing information from multiple sources "
            "into coherent, well-structured reports. You identify key themes, "
            "compare perspectives, and highlight important insights."
        ),
        llm=llm,
        verbose=True,
    )

    # Task 1: Search for information on a topic
    search_task = Task(
        description=(
            "Search for recent information about 'AI agents in production' using Brave Search. "
            "Find 2-3 high-quality URLs from reputable sources (tech blogs, documentation, "
            "research papers). Return the URLs with brief descriptions of what each source covers."
        ),
        expected_output="A list of 2-3 URLs with descriptions of their content.",
        agent=researcher,
    )

    # Task 2: Extract content from the found URLs
    extract_task = Task(
        description=(
            "Take the URLs provided by the researcher and scrape the content from each page. "
            "Extract the main points and key information from each source. "
            "Focus on practical insights about deploying AI agents."
        ),
        expected_output="Extracted content summaries from each URL.",
        agent=extractor,
        context=[search_task],
    )

    # Task 3: Synthesize into a final report
    synthesize_task = Task(
        description=(
            "Using the extracted content from all sources, create a brief synthesis report "
            "about 'AI agents in production'. Include: key themes across sources, "
            "practical recommendations, and any contrasting viewpoints."
        ),
        expected_output="A 2-3 paragraph synthesis report with key insights.",
        agent=synthesizer,
        context=[extract_task],
    )

    # Create and run the crew
    crew = Crew(
        agents=[researcher, extractor, synthesizer],
        tasks=[search_task, extract_task, synthesize_task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()
    print(f"\n{'='*60}")
    print("FINAL REPORT")
    print('='*60)
    print(result)


if __name__ == "__main__":
    main()