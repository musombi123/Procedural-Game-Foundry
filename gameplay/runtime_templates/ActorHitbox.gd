extends Area3D
var actor: Node3D
func configure(target_actor: Node3D) -> void:
    actor = target_actor
func take_damage(amount: int) -> void:
    if is_instance_valid(actor) and actor.has_method("take_damage"):
        actor.take_damage(amount)
