"""
CrewAI Advanced Tools Example

This example demonstrates using multiple search tools in a CrewAI workflow:
- SerperDevTool: Web search via Serper API
- ParallelSearchTool: LLM-optimized web search via Parallel AI

Required API keys (set as environment variables):
- SERPER_API_KEY: Get from https://serper.dev/
- PARALLEL_API_KEY: Get from https://parallel.ai/
- ANTHROPIC_API_KEY: For the LLM

To run:
    export SERPER_API_KEY=your_key
    export PARALLEL_API_KEY=your_key
    export ANTHROPIC_API_KEY=your_key
    so-record example_workflows/debug_examples/crewai_advanced_tools.py
"""

from crewai import Agent, Task, Crew, Process, LLM
from crewai_tools import SerperDevTool, ParallelSearchTool


def main():
    llm = LLM(
        model="claude-sonnet-4-5",
        max_tokens=1024,
    )

    # Initialize search tools
    serper_search = SerperDevTool()
    parallel_search = ParallelSearchTool()

    # Agent 1: Uses Serper for web search
    serp_researcher = Agent(
        role="Web Research Analyst",
        goal="Find relevant search engine results on topics",
        backstory=(
            "You are an expert at using search engines to find authoritative "
            "sources and recent information. You specialize in finding diverse "
            "perspectives from web search results."
        ),
        tools=[serper_search],
        llm=llm,
        verbose=True,
    )

    # Agent 2: Uses Parallel for LLM-optimized search
    parallel_researcher = Agent(
        role="Deep Research Analyst",
        goal="Conduct deep web research with LLM-optimized results",
        backstory=(
            "You are a thorough researcher who uses advanced search tools "
            "that return content optimized for AI analysis. You excel at "
            "extracting key insights from search results."
        ),
        tools=[parallel_search],
        llm=llm,
        verbose=True,
    )

    # Agent 3: Synthesizes research into a report
    synthesizer = Agent(
        role="Research Synthesizer",
        goal="Combine research from multiple sources into comprehensive reports",
        backstory=(
            "You are skilled at synthesizing information from multiple research "
            "sources into clear, well-structured reports. You identify key themes "
            "and provide actionable insights."
        ),
        llm=llm,
        verbose=True,
    )

    # Task 1: Web search using Serper
    serp_task = Task(
        description=(
            "Use Serper search to find recent news and articles about "
            "'AI agent frameworks comparison 2024'. Focus on finding 3-5 relevant results "
            "and summarize what each source discusses."
        ),
        expected_output="A list of 3-5 search results with brief descriptions of each.",
        agent=serp_researcher,
    )

    # Task 2: Deep search using Parallel
    parallel_task = Task(
        description=(
            "Use Parallel search to research 'best practices for building AI agents'. "
            "Set the objective to find practical implementation guidelines and "
            "return up to 5 results."
        ),
        expected_output="Key findings from the search about AI agent best practices.",
        agent=parallel_researcher,
    )

    # Task 3: Synthesize both research sources
    synthesis_task = Task(
        description=(
            "Combine the research from both the SERP search and the Parallel search "
            "into a comprehensive summary about the current state of AI agent frameworks "
            "and best practices. Include key trends and recommendations."
        ),
        expected_output="A 2-3 paragraph synthesis report combining insights from both sources.",
        agent=synthesizer,
        context=[serp_task, parallel_task],
    )

    # Create and run the crew
    crew = Crew(
        agents=[serp_researcher, parallel_researcher, synthesizer],
        tasks=[serp_task, parallel_task, synthesis_task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()
    print(f"\n{'='*60}")
    print("FINAL RESULT")
    print('='*60)
    print(result)


if __name__ == "__main__":
    main()
