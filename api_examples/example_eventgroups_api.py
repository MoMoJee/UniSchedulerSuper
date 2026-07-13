"""Planner V2 personal Event Group CRUD example."""

from client import authenticated_client


def main() -> None:
    client = authenticated_client()
    created = client.json(
        "POST", "/api/v2/groups/",
        json={"name": "API 示例组", "description": "临时分组", "color": "#4ECDC4"},
    )["group"]
    print("created:", created)

    updated = client.json(
        "PATCH",
        f"/api/v2/groups/{created['group_id']}/",
        json={"expected_version": created["version"], "name": "API 示例组（已更新）"},
    )["group"]
    print("updated:", updated)

    listed = client.json("GET", "/api/v2/groups/")
    print("count:", listed["count"])

    deleted = client.json(
        "DELETE",
        f"/api/v2/groups/{updated['group_id']}/",
        json={"expected_version": updated["version"], "delete_items": False},
    )
    print("deleted:", deleted)


if __name__ == "__main__":
    main()
