def record_permission_change(actor_id: str, target_id: str, new_role: str) -> None:
    apply_role(target_id, new_role)
    try:
        audit_log.write(actor=actor_id, target=target_id, role=new_role)
    except Exception:
        pass
