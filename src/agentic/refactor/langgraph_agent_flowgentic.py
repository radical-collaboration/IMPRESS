"""
Product Research Assistant - Extended Supervisor Pattern

This example demonstrates an advanced supervisor pattern with:
- Parallel LLM-based worker agents
- Conditional synthesis based on audience context
- Two different synthesizer strategies

Flow:
  START → router → [tech_agent || reviews_agent] → gather → synthesis_router
        → [technical_synthesizer OR consumer_synthesizer] → END
"""

import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
import sys
from typing import Annotated, Dict, List, Optional, TypedDict, Literal, Annotated
import logging
import time
import operator
import itertools

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field

from radical.asyncflow import ConcurrentExecutionBackend
from radical.asyncflow import DragonTelemetryCollector
from radical.asyncflow import DragonVllmInferenceBackend
from radical.asyncflow import DragonExecutionBackendV3, WorkflowEngine
from radical.asyncflow.logging import init_default_logger

from flowgentic.langGraph.execution_wrappers import AsyncFlowType
from flowgentic.langGraph.main import LangraphIntegration
from flowgentic.langGraph.utils.supervisor import create_llm_router, supervisor_fan_out
from flowgentic.utils.llm_providers import ChatLLMProvider

import multiprocessing as mp

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


# Define the state schema
class GraphState(TypedDict):
    """State schema for the agent."""
    query: str
    selected_tool: str
    tool_output: str
    messages: Annotated[list[str], operator.add]


# Define structured output for router
class RouterOutput(BaseModel):
    """Structured output from the router node."""
    tool_name: Literal["search_tool_node", "calculator_tool_node", "database_tool_node"] = Field(
        description="The name of the tool to route to"
    )
    reasoning: str = Field(
        description="Brief explanation of why this tool was selected"
    )


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(threadName)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    
    mp.set_start_method("dragon")

    # Step-1 Create Dragon backend
    print("    # Step-1 Create Dragon backend")
    nodes = 1  # Total nodes in allocation
    backend = await DragonExecutionBackendV3(
        num_workers=1,
        disable_background_batching=False)

    num_services = 1
    nodes_per_service = 1
    services = []

    logger.info(f"Creating {num_services} VLLM services...")

    # Step-2 make multiple VLLM services (or 1 in Mason's case)
    print("    #Step-2 make multiple VLLM services (or 1 in Mason's case)")
    for i in range(num_services):
        port = 8000 + i
        offset = i * nodes_per_service  # Each pipeline starts at different node

        logger.info(f"Service {i+1}: port={port}, offset={offset}, num_nodes={nodes_per_service}")

        service = DragonVllmInferenceBackend(
            config_file="/anvil/scratch/x-mason/IMPRESS/src/agentic/refactor/config.yaml",
            model_name="/anvil/scratch/x-mason/.cache/huggingface/hub/models/hub/models--meta-llama--Llama-3.1-8B-Instruct/snapshots/0e9e39f249a16976918f6564b8830bc894c89659/",
            num_nodes=nodes_per_service,
            num_gpus=1,
            tp_size=1,
            port=port,
            offset=offset  # Change this to control the number of nodes each inference pipeline takes
        )

        services.append(service)
    
    # Step-3 make sure to await for all services to be initialized before any agentic calls
    # Initialize ALL services concurrently
    print("    # Step-3 make sure to await for all services to be initialized before any agentic calls")
    print("    # Initialize ALL services concurrently")
    logger.info(f"Initializing all {num_services} services concurrently...")
    await asyncio.gather(*[service.initialize() for service in services])

    # Get endpoints
    service_endpoints = [service.get_endpoint() for service in services]


    collector = DragonTelemetryCollector(
        collection_rate=1.0,              # Collect every second
        checkpoint_interval=30.0,         # Checkpoint every 30 seconds
        checkpoint_dir=os.path.join(os.getcwd(), 'telemetry-results'),  # Save checkpoints here
        checkpoint_count=10,              # Keep last 10 checkpoints
        enable_cpu=True,
        enable_gpu=True,
        enable_memory=True,
        metric_prefix="infer-asyncflow"   # Prefix all metrics
    )

    # Start collection (spawns processes on all nodes)
    collector.start()

    logger.info(f"All {num_services} services initialized")
    logger.info("Node allocation:")
    for i in range(num_services):
        offset = i * nodes_per_service
        logger.info(f"Service {i+1}: nodes[{offset}:{offset+nodes_per_service}] -> {service_endpoints[i]}")

    # Create round-robin load balancer
    endpoint_cycle = itertools.cycle(service_endpoints)

    graph = StateGraph(GraphState)

    async with LangraphIntegration(backend=backend) as agents_manager:
        # ================================================================
        # STEP 0: Register agents tools
        # ================================================================

        @agents_manager.execution_wrappers.asyncflow(
            flow_type=AsyncFlowType.AGENT_TOOL_AS_FUNCTION
        )
        async def search_tool_node(state: GraphState) -> GraphState:
            """Tool node for search operations."""
            user_input = state["input"]
            # Simulate search operation
            result = f"Search results for: '{user_input}'"
            
            return {
                **state,
                "tool_output": result,
                "messages": [f"SearchTool: Executed search for '{user_input}'"]
            }

        @agents_manager.execution_wrappers.asyncflow(
            flow_type=AsyncFlowType.AGENT_TOOL_AS_FUNCTION
        )
        async def calculator_tool_node(state: GraphState) -> GraphState:
            """Tool node for calculation operations."""
            user_input = state["input"]
            # Simulate calculation
            result = f"Calculation completed for: '{user_input}'"
            
            return {
                **state,
                "tool_output": result,
                "messages": [f"CalculatorTool: Performed calculation"]
            }
        
        @agents_manager.execution_wrappers.asyncflow(
            flow_type=AsyncFlowType.AGENT_TOOL_AS_FUNCTION
        )
        async def database_tool_node(state: GraphState) -> GraphState:
            """Tool node for database operations."""
            user_input = state["input"]
            # Simulate database query
            result = f"Database query results for: '{user_input}'"
            
            return {
                **state,
                "tool_output": result,
                "messages": [f"DatabaseTool: Executed database query"]
            }


        @agents_manager.execution_wrappers.asyncflow(
            flow_type=AsyncFlowType.EXECUTION_BLOCK
        )
        async def router_node(state: GraphState) -> dict:
            """
            Router node that uses an LLM to analyze input and decide which tool to use.
            Returns structured output indicating the selected tool.
            """
            user_input = state["query"]
            
            routing_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a routing agent that decides which tool to use based on user input.

        Available tools:
        1. search_tool_node: Use for searching information, looking up facts, finding content on the web, or general queries
        2. calculator_tool_node: Use for mathematical calculations, computations, arithmetic operations, or numerical analysis
        3. database_tool_node: Use for database queries, data retrieval, storing/fetching records, or data management operations
        
        ## Response Format
        You MUST respond with ONLY a valid JSON object in this exact format:
        {
          "next_task": "<one of: search_tool_node, calculator_tool_node, database_tool_node, run_alphafold, score_alphafold, END>",
          "reasoning": "<brief explanation of your choice>"
        }

        Do not include any other text before or after the JSON object."""),
                ("user", "{input}")
            ])
            
            # Get LLM with structured output
            llm = next(endpoint_cycle)
            structured_llm = llm.with_structured_output(RouterOutput)
            
            # Create the chain
            routing_chain = routing_prompt | structured_llm
            
            # Invoke the LLM to get routing decision
            try:
                routing_decision = await routing_chain.ainvoke({"input": user_input})
                selected_tool = routing_decision.tool_name
                reasoning = routing_decision.reasoning
            except Exception as e:
                # Fallback to search tool if LLM call fails
                print(f"Warning: LLM routing failed ({str(e)}), defaulting to search_tool")
                selected_tool = "search_tool"
                reasoning = f"Fallback due to error: {str(e)}"
            
            return {
                **state,
                "selected_tool": selected_tool,
                "messages": [f"Router: Selected {selected_tool}. Reasoning: {reasoning}"]
            }
        # ================================================================
        # Conditional Edge Functions
        # ================================================================

        def route_to_tool(state: GraphState) -> str:
            """
            Determines which tool node to route to based on the router's decision.
            """
            selected_tool = state.get("selected_tool")
            logging.info(f"🔀 Routing to: {selected_tool}")
            return selected_tool

        # ================================================================
        # STEP 6: Build the Graph with Introspection
        # ================================================================

        # Wrap nodes for introspection
        router_intro = agents_manager.agent_introspector.introspect_node(
            router_node, "router_node"
        )
        search_tool_intro = agents_manager.agent_introspector.introspect_node(
            search_tool_node, "search_tool_node"
        )
        calculator_tool_intro = agents_manager.agent_introspector.introspect_node(
            calculator_tool_node, "calculator_tool_node"
        )
        database_tool_intro = agents_manager.agent_introspector.introspect_node(
            database_tool_node, "database_tool_node"
        )

        # Register all nodes for report generation
        agents_manager.agent_introspector._all_nodes = [
            "router_node_node",
            "search_tool_node",
            "calculator_tool_node",
            "database_tool_node",
        ]

        graph.add_node("router_node", router_intro)
        graph.add_node("search_tool_node", search_tool_intro)
        graph.add_node("calculator_tool_node", calculator_tool_intro)
        graph.add_node("database_tool_node", database_tool_intro)

        graph.add_edge(START, "router_node")

        graph.add_edge("search_tool_node", "router_node")
        graph.add_edge("calculator_tool_node", "router_node")
        graph.add_edge("database_tool_node", "router_node")

        graph.add_conditional_edges(
            "router_node",
            route_to_tool,
            {
                "search_tool_node": "search_tool_node",
                "calculator_tool_node": "calculator_tool_node",
                "database_tool_node": "database_tool_node"
            }        
        )

        app = graph.compile()

        # ================================================================
        # STEP 7: Test the Workflow
        # ================================================================

        test_queries = [
            "Search for the latest news on AI developments",
            "What is 25 * 4 + 10 divided by 2?",
            "Retrieve all user records from the customers table",
            "What is the weather today?",
            "I need to compute the compound interest for a loan",
            "Store this information in the database: user ID 12345",
            "Find articles about quantum computing"
        ]
        
        print("=" * 60)
        print("LangGraph Agent with LLM-Powered Router - Demo")
        print("=" * 60)

        for query in test_queries:
            print("\n" + "=" * 100)
            logging.info(f"🚀 TESTING QUERY: '{query}'")
            print("=" * 100)

            wall_start = time.perf_counter()

            result = None
            try:
                state = GraphState(query=query)
                result = await app.ainvoke(state)
                wall_ms = (time.perf_counter() - wall_start) * 1000

            except Exception as e:
                logging.error(f"❌ Workflow execution failed: {str(e)}")
                raise
            finally:
                # Generate execution artifacts (report, graph)
                if result is not None:
                    await agents_manager.generate_execution_artifacts(
                        app, __file__, final_state=result
                    )
                else:
                    logger.warning("Result from execution are none")

            # Display results
            print(f"\n{'=' * 100}")
            print(f"📊 EXECUTION RESULTS")
            print(f"{'=' * 100}")
            print(f"Query: {result['query']}")
            print(f"Worker Agents Called: {result['routing_decision']}")
            print(f"Routing Rationale: {result['routing_rationale']}")
            print(f"Audience Type: {result['audience_type']}")
            print(f"Synthesizer Used: {result['synthesis_decision']}")
            print(f"\n{'─' * 100}")
            print(f"📄 FINAL REPORT:")
            print(f"{'─' * 100}")
            print(result.get("final_report", "N/A"))
            print(f"\n{'─' * 100}")
            logging.info(f"⏱️  TOTAL WALL TIME: {wall_ms:.1f}ms")
            print(f"{'=' * 100}\n")


if __name__ == "__main__":
    asyncio.run(main())


