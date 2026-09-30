from sentinel.api.auth import ROLE_PERMISSIONS, Permission, Role, hash_key


def test_permission_matrix() -> None:
    assert ROLE_PERMISSIONS[Role.VIEWER] == {Permission.READ}
    assert ROLE_PERMISSIONS[Role.INVESTIGATOR] == {Permission.READ, Permission.REVIEW}
    assert ROLE_PERMISSIONS[Role.ADMIN] == set(Permission)
    assert ROLE_PERMISSIONS[Role.SERVICE] == {Permission.INGEST}  # machines only submit events


def test_keys_are_hashed_not_stored() -> None:
    digest = hash_key("sk_example")
    assert digest != "sk_example" and len(digest) == 64
    assert hash_key("sk_example") == digest
