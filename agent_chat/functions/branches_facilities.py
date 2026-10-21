from dashboard.models.branches_facilities import Branch, Facility
from langchain.tools import tool


@tool(response_format="content_and_artifact")
def get_branch(branch: str | None) -> list[dict]:
    """Search the branches informations.
    
    Args:
        branch: Name of branch. If None then it return list of branches
    """

    result = []
    branch_rows = Branch.objects.filter(name=branch) if branch is not None else Branch.objects.all()

    for row in branch_rows:
        result.append({
            'name': row.name,
            'facilities_count': 20
        })

