class AnyType(str):
    def __eq__(self, _other):
        return True

    def __ne__(self, _other):
        return False


ANY = AnyType("*")


class ImpactSwitch:
    """Minimal functional clone of ComfyUI-Impact-Pack's GeneralSwitch
    (class_type "ImpactSwitch"), covering only what the AIO Krea2 workflow
    actually uses: pick input{select} and pass it through. Installed as a
    tiny local node instead of the full Impact-Pack to avoid its heavy
    segment-anything/scikit-image/sam2 dependency tree for one utility node.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "select": ("INT", {"default": 1, "min": 1, "max": 999999}),
                "sel_mode": ("BOOLEAN", {"default": True}),
            },
            "optional": {f"input{i}": (ANY,) for i in range(1, 11)},
        }

    RETURN_TYPES = (ANY, "STRING", "INT")
    RETURN_NAMES = ("selected_value", "selected_label", "selected_index")
    FUNCTION = "doit"
    CATEGORY = "shim"

    def doit(self, select=1, sel_mode=True, **kwargs):
        value = kwargs.get(f"input{select}")
        return (value, "", select)


NODE_CLASS_MAPPINGS = {"ImpactSwitch": ImpactSwitch}
NODE_DISPLAY_NAME_MAPPINGS = {"ImpactSwitch": "Switch (Any) [shim]"}
