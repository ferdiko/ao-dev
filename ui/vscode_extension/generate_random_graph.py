import json
import random
import uuid
import socket
import os
from typing import Dict


def generate_random_dag(num_nodes: int, num_edges: int, seed: int = None) -> Dict:
    """
    Generate a random directed acyclic graph (DAG) with specified number of nodes and edges.

    Args:
        num_nodes: Number of nodes in the graph
        num_edges: Number of edges in the graph
        seed: Random seed for reproducibility (optional)

    Returns:
        Dictionary containing nodes and edges in the specified format
    """
    if seed is not None:
        random.seed(seed)

    # Validate input
    max_edges = num_nodes * (num_nodes - 1) // 2  # Maximum edges in a DAG
    if num_edges > max_edges:
        raise ValueError(f"Too many edges requested. Maximum for {num_nodes} nodes is {max_edges}")

    if num_edges < 0:
        raise ValueError("Number of edges cannot be negative")

    if num_nodes < 1:
        raise ValueError("Number of nodes must be at least 1")

    # Generate nodes
    nodes = []
    node_ids = []

    for i in range(num_nodes):
        node_id = str(uuid.uuid4())
        node_ids.append(node_id)

        # Generate sample content for the node
        sample_inputs = [
            f"Process item {i+1}",
            f"Calculate value for node {i+1}",
            f"Execute task {i+1}",
            f"Generate output {i+1}",
            f"Transform data {i+1}",
        ]

        sample_outputs = [
            f"Result {i+1}",
            f"Output {random.randint(1, 100)}",
            f"Processed data {i+1}",
            f"Value: {random.randint(10, 999)}",
            f"Task {i+1} completed",
        ]

        node = {
            "id": node_id,
            "input": random.choice(sample_inputs),
            "output": random.choice(sample_outputs),
            "border_color": "#FFC000",
            "label": "undefined_model",
            "stack_trace": f'File "/path/to/code/node_{i+1}.py", line {random.randint(10, 100)}, in main',
            "model": "undefined_model",
            "attachments": [],
        }
        nodes.append(node)

    # Generate edges ensuring no cycles
    edges = []

    # Create a topological ordering to ensure DAG property
    # We'll use node indices and only allow edges from lower to higher indices
    possible_edges = []
    for i in range(num_nodes):
        for j in range(i + 1, num_nodes):
            possible_edges.append((i, j))

    # Randomly sample edges from possible edges
    if num_edges > 0:
        selected_edge_indices = random.sample(possible_edges, min(num_edges, len(possible_edges)))

        for source_idx, target_idx in selected_edge_indices:
            source_id = node_ids[source_idx]
            target_id = node_ids[target_idx]

            edge_id = f"e{source_id}-{target_id}"
            edge = {"id": edge_id, "source": source_id, "target": target_id}
            edges.append(edge)

    return {"nodes": nodes, "edges": edges}


def connect_to_main_server(host="127.0.0.1", port=5959):
    """Connect to the develop server and return the connection."""
    try:
        conn = socket.create_connection((host, port), timeout=5)
        return conn
    except Exception as e:
        print(f"Failed to connect to develop server: {e}")
        return None


def send_message(conn: socket.socket, message: dict) -> None:
    """Send a JSON message to the server."""
    try:
        msg_str = json.dumps(message) + "\n"
        conn.sendall(msg_str.encode("utf-8"))
    except Exception as e:
        print(f"Error sending message: {e}")


def receive_message(conn: socket.socket) -> dict:
    """Receive a JSON message from the server."""
    try:
        file_obj = conn.makefile(mode="r")
        response_line = file_obj.readline()
        if response_line:
            return json.loads(response_line.strip())
    except Exception as e:
        print(f"Error receiving message: {e}")
    return {}


def send_graph_to_ui(graph: Dict, graph_name: str = "Random Graph"):
    """Send a generated graph to the develop server to display in the UI."""
    conn = connect_to_main_server()
    if not conn:
        print("Could not connect to develop server")
        return None

    try:
        # Send handshake as agent-runner
        handshake = {
            "type": "hello",
            "role": "agent-runner",
            "name": graph_name,
            "cwd": os.getcwd(),
            "command": f"python {__file__}",
            "environment": dict(os.environ),
            "prev_session_id": None,
        }
        send_message(conn, handshake)

        # Receive session_id from server
        session_response = receive_message(conn)
        session_id = session_response.get("session_id")
        if not session_id:
            print("Failed to get session_id from server")
            return None

        print(f"Got session_id: {session_id}")

        # Send each node individually with add_node messages
        for node in graph["nodes"]:
            # Find incoming edges for this node
            incoming_edges = [
                edge["source"] for edge in graph["edges"] if edge["target"] == node["id"]
            ]

            add_node_msg = {
                "type": "add_node",
                "session_id": session_id,
                "node": node,
                "incoming_edges": incoming_edges,
            }
            send_message(conn, add_node_msg)

        # Mark the experiment as finished
        deregister_msg = {"type": "deregister", "session_id": session_id}
        send_message(conn, deregister_msg)

        print(
            f"Successfully sent graph '{graph_name}' with {len(graph['nodes'])} nodes and {len(graph['edges'])} edges to UI"
        )
        return session_id

    except Exception as e:
        print(f"Error sending graph to UI: {e}")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    """Example usage of the random DAG generator."""
    # Generate randome example graph
    random_graph = generate_random_dag(num_nodes=50, num_edges=60)

    # Send graph to UI for display
    print("Sending graph to UI...")
    send_graph_to_ui(random_graph, "Random Graph")


if __name__ == "__main__":
    main()
