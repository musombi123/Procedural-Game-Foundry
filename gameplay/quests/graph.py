"""Quest dependency graph validation; quest text and rewards remain authored data."""
from collections import defaultdict,deque

def validate_quest_graph(nodes: list[dict]) -> dict:
    ids={n.get("id") for n in nodes}
    errors=[]; graph=defaultdict(list); indegree={node:0 for node in ids}
    if None in ids: errors.append("Every quest node needs an id")
    for node in nodes:
        node_id=node.get("id")
        for dep in node.get("requires",[]):
            if dep not in ids: errors.append(f"{node_id} requires missing quest {dep}")
            else: graph[dep].append(node_id); indegree[node_id]+=1
    queue=deque(n for n,d in indegree.items() if d==0); visited=0
    while queue:
        current=queue.popleft(); visited+=1
        for nxt in graph[current]:
            indegree[nxt]-=1
            if indegree[nxt]==0: queue.append(nxt)
    if visited!=len(ids): errors.append("Quest dependency cycle detected")
    return {"valid":not errors,"errors":errors}
