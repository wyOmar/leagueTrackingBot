import io
import os
from PIL import Image

def make_champion_with_role_icon(champion_name: str, role: str) -> Image.Image:
    """Overlays a role icon onto a champion portrait. Returns a PIL Image object."""
    role_map = {
        "TOP": "Top",
        "JUNGLE": "Jungle",
        "MIDDLE": "Middle",
        "BOTTOM": "Bottom",
        "UTILITY": "Support"
    }
    role_file = role_map.get(role.upper())

    champ_path = f"assets/champion/{champion_name}.png"
    
    try:
        if os.path.exists(champ_path):
            base_img = Image.open(champ_path).convert("RGBA")
        else:
            base_img = Image.new("RGBA", (120, 120), (40, 40, 40, 255))
            
        if role_file:
            role_path = f"assets/icons/{role_file}_icon.png"
            if os.path.exists(role_path):
                role_img = Image.open(role_path).convert("RGBA")
                role_size = (int(base_img.width * 0.35), int(base_img.height * 0.35))
                role_img = role_img.resize(role_size, Image.Resampling.LANCZOS)
                
                offset = (base_img.width - role_img.width, base_img.height - role_img.height)
                base_img.paste(role_img, offset, role_img)
                
        return base_img
        
    except Exception as e:
        print(f"Image generation failed: {e}")
        return Image.new("RGBA", (120, 120), (40, 40, 40, 255))


def make_grouped_champion_images(players_data: list[tuple[str, str]]) -> io.BytesIO:
    """
    Takes a list of (champion_name, role) tuples.
    Generates their icons and aligns them in a centered grid layout.
    """
    images = []
    for champ_name, role in players_data:
        images.append(make_champion_with_role_icon(champ_name, role))
        
    if not images:
        return io.BytesIO()

    num_images = len(images)
    
    if num_images == 1:
        layout = [1]
    elif num_images == 2:
        layout = [2]
    elif num_images == 3:
        layout = [2, 1]
    elif num_images == 4:
        layout = [2, 2]
    else: 
        layout = [3, 2]

    img_w, img_h = images[0].width, images[0].height
    max_cols = max(layout)
    
    canvas_width = max_cols * img_w
    canvas_height = len(layout) * img_h
    
    combined_img = Image.new("RGBA", (canvas_width, canvas_height))
    
    img_idx = 0
    for row_idx, row_count in enumerate(layout):
        row_width = row_count * img_w
        start_x = (canvas_width - row_width) // 2
        start_y = row_idx * img_h
        
        for col_idx in range(row_count):
            if img_idx < num_images:
                img = images[img_idx]
                combined_img.paste(img, (start_x + (col_idx * img_w), start_y))
                img_idx += 1
                
    out_bytes = io.BytesIO()
    combined_img.save(out_bytes, format="PNG")
    out_bytes.seek(0)
    
    return out_bytes