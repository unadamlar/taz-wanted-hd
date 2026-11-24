"""Per-level data for the look: what a new level has to supply. Shared code is dress.py, kit.py, export.py."""

# texture (material base name) -> role. First match wins. Unmatched -> "lit".
ZOO_RULES = [
    # gameplay objects keep the game's own look (lit, textured), never dressed or buried
    ("zoohub/textures/tazbook*", "gameplay"), ("zoohub/textures/tazwanted", "gameplay"),
    ("zoohub/textures/tazanted02", "gameplay"), ("zoohub/textures/animalcrate*", "gameplay"),
    ("zoohub/textures/bananacrate*", "gameplay"), ("zoohub/textures/dinghy*", "gameplay"),
    ("zoohub/textures/hitsignexplan", "gameplay"), ("zoohub/textures/zoosign*", "gameplay"),
    ("zoohub/textures/tazcagelock*", "gameplay"), ("zoohub/extras/tazcagelock*", "gameplay"),
    ("resobjs/*", "gameplay"),
    # ground: path strips carry the lawn's jagged fringe painted in their texture
    ("zoohub/textures/zoohubpathaqua", "lit"), ("zoohub/textures/zoohubpathice", "lit"),
    ("zoohub/textures/zoohubpathisaf", "lit"),
    ("zoohub/textures/zoohubbankedge", "ground"),   # the moat's zigzag bank is the same paint as the path strips
    ("zoohub/textures/zoohubpath*", "ground"), ("zoohub/textures/zoopathjoiner", "ground"),
    ("zoohub/textures/hubpath02", "ground"),
    ("zoohub/textures/zoohubgrass*", "lawn"), ("zoohub/textures/hubflowers04", "lawn"),
    ("zoohub/textures/grassjoiner", "lawn"), ("zoohub/textures/grassedge*", "lawn"),
    ("zoohub/textures/tazcagegrass", "lawn"),
    ("zoohub/textures/safrockcream*", "cliff"),
    ("zoohub/textures/safrock[0-9]*", "lit"),       # the lilac mountain keeps its own lilac look
    ("zoohub/textures/zoohubwall2", "lit"),         # cream lamp globes / caps: not brick, not trim
    ("zoohub/textures/zoohubpiller*", "brick"), ("zoohub/textures/zoohubwall*", "brick"),
    ("zoohub/textures/hutbrick*", "brick"), ("zoohub/textures/tower", "brick"),
    ("zoohub/textures/safariwater", "water"), ("zoohub/textures/water", "water"),
    # replaced: cards and props swapped for kit geometry
    ("zoohub/textures/grassy", "hide"),            # drip cards -> kit vines along cliff tops
    ("zoohub/textures/snowbeam07", "fence_rail"),   # rail cards -> kit fences along their top edge
    ("zoohub/textures/metaledges", "fence_post"), ("zoohub/textures/tazcage3", "fence_cap"),
    ("zoohub/textures/tazwood02a", "tree"), ("zoohub/textures/tazfern05*", "tree"),
    ("zoohub/skybox/*", "sky"),                     # kept as a far hill band; its painted sky is cut away
    ("resTex/shadowsub", "hide"),                  # baked blob shadow: real shadows now
]

# Hand-placed / hand-tuned items. Keep this short and count it in the report.
ZOO_HAND = {
    "camera_B": dict(loc=(6.0, -8.0, -15.3), look_at=(4.0, -19.5, -15.8), lens=15.0),
    "taz_offset_B": (13.3, 7.4, 0.0),  # move Taz onto the path in front of camera B
    "elephant_offset_B": (0.0, 0.0, 0.0),
    "camera_C": dict(loc=(2.8, -4.0, -13.8), look_at=(-4.5, -13.5, -17.4), lens=17.0),  # water view
}
# Per-level look settings (one block per level). Sun: compass angle it shines FROM
# (0 = +X, 90 = +Y). Pass 1 followed the baked shadows (280/40); pass 2 puts it on
# camera B's side, upper left, so faces toward the player are lit.
ZOO_LOOK = dict(
    sun=dict(sun_azimuth=45.0, sun_elevation=38.0, sun_strength=5.2, sun_color="#fff0d6"),
    grade=dict(exposure=0.45, look="AgX - Punchy", saturation=1.28, bloom=0.4, fog=0.07, fog_start=30.0, fog_depth=160.0,
               ambient_strength=1.0),
    sky=dict(zenith="#1257e6", horizon="#8fd0ff", horizon_warm="#fff4e2", sky_strength=1.3, cloud_white=1.35,
             ambient="#cdd8ea"),
    cliff=dict(top_min_z=-15.2, dilate=0.35, band=(0.8, 1.7), ledge=0.6, erosion=0.2, top_break=0.22),
)
ZOO_HDRI = "polyhaven/ph-kloofendal_48d_partly_cloudy_puresky/content/kloofendal_48d_partly_cloudy_puresky_4k.hdr"
ZOO_PASS1 = dict(sun=dict(sun_azimuth=280.0, sun_elevation=40.0),
             grade=dict(exposure=0.3, ambient_strength=1.1, fog_start=22.0, fog_depth=120.0), sky={})

# Game paint kept, with a tiling material's relief and grain multiplied in: scenery no rule replaces.
ZOO_DETAIL = [
    ("zoohub/textures/orangerock*", "d_rock"), ("zoohub/textures/orangeextra*", "d_rock"),
    ("zoohub/textures/safrock[0-9]*", "d_rock"), ("zoohub/textures/sharprock*", "d_rock"),
    ("zoohub/textures/safaritemple*", "d_stone"), ("zoohub/extras/aquasandcas*", "d_stone"),
    ("zoohub/textures/aquasandcas*", "d_stone"), ("zoohub/textures/aquaseawall*", "d_stone"),
    ("zoohub/textures/icecubed*", "d_ice"), ("zoohub/textures/igloo*", "d_ice"),
    ("zoohub/textures/sdomestrip*", "d_ice"), ("zoohub/textures/snowxmas*", "d_ice"), ("zoohub/textures/icewalkway", "d_ice"),
    ("zoohub/textures/aquasandjoiner*", "d_stone"), ("zoohub/textures/snowbeam*", "d_stone"), ("zoohub/textures/zoohubwall2", "d_stone"),
    ("zoohub/textures/tower*", "d_stone"), ("zoohub/textures/electricfencewall*", "d_stone"),
]
ZOO_TILES = {
    "d_rock": dict(set="rock061", period=3.0, px=1024, detail=0.75, triplanar=True, rough=0.85),
    "d_stone": dict(set="old_sandstone", period=2.6, px=1024, detail=0.7, triplanar=True, rough=0.8),
    "d_ice": dict(set="boulder_dry", period=4.5, px=1024, detail=0.12, triplanar=True, rough=0.35, normal=0.35),
}

# ---- city hub (scene 8): night. The game's colour is blue light baked into vertices over pale textures.
CITY_RULES = [
    ("resobjs/*", "gameplay"), ("cityhub/textures/tazbook*", "gameplay"), ("cityhub/textures/tazcage*", "gameplay"),
    ("cityhub/extras/*", "gameplay"), ("cityhub/textures/tazwanted", "gameplay"), ("cityhub/textures/tazanted02", "gameplay"),
    ("cityhub/textures/bombbit*", "transient"),      # debris caught mid-air in the capture: must not keep grass away
    ("cityhub/textures/citytarmac6", "lit"),         # kerb sides, not road
    ("cityhub/textures/citytarmac*", "road"), ("cityhub/textures/citypave*", "ground"),
    ("cityhub/textures/citybloom*", "lawn"), ("cityhub/textures/lampostcurl", "lamp"),
    ("cityhub/skybox/*", "sky"), ("resTex/shadowsub", "hide"),
]
CITY_HAND = {
    "camera_B": dict(loc=(-9.0, 2.0, -20.6), look_at=(14.0, 8.0, -19.0), lens=16.0),   # across the junction to the museum
    "camera_C": dict(loc=(8.0, -8.0, -21.0), look_at=(-8.0, 12.0, -18.5), lens=16.0),  # along the street
    "taz_offset_B": (0.0, 0.0, 0.0), "elephant_offset_B": (0.0, 0.0, 0.0),
}
CITY_LOOK = dict(
    sun=dict(sun_azimuth=242.0, sun_elevation=35.0, sun_strength=1.45, sun_color="#a9c0ff"),  # from the painted moon's side, raised
    grade=dict(exposure=0.3, look="AgX - Punchy", saturation=1.2, bloom=0.9, fog=0.25, fog_start=40.0, fog_depth=200.0,
               ambient_strength=0.5),
    sky=dict(zenith="#0a1540", horizon="#20366f", horizon_warm="#31407a", sky_strength=1.0, cloud_white=0.3, ambient="#7a8fc8"),
    cliff=dict(),
)
CITY_LAMPS = dict(color="#ffd08a", power=5.5, radius=14.0, drop=0.7, cone=0.8, pool_power=1.0, pool_radius=8.0, pool_height=3.2, pool_cone=-0.2,
                  extra=((-34.5, 4.0, -19.2, 13.0, "#e6f0ff", 3.0),))  # the supermarket's forecourt: white light the warm-pool rule misses
CITY_GLOW = [  # texture pattern, strength, brightness range that glows (None = the whole texture)
    ("cityhub/textures/chubdept01", 0.5, None), ("cityhub/textures/glass01", 0.3, None), ("cityhub/textures/market0*", 0.4, None),
    ("cityhub/textures/chubsamshop01.gif", 0.55, None), ("cityhub/textures/chubsafe0[6-9]", 0.55, None),  # the supermarket: signs, windows, giant cart
    ("cityhub/textures/deptlight*", 0.55, (0.55, 0.8)),   # big flat shop doors: a full glow reads as a white wall
    ("cityhub/textures/*neon*", 2.2, None), ("cityhub/textures/*light*", 2.4, (0.45, 0.7)), ("cityhub/textures/*bulb*", 2.6, (0.4, 0.65)),
    ("cityhub/textures/wineon*", 2.0, None), ("cityhub/textures/winstar*", 1.8, (0.3, 0.6)), ("cityhub/textures/*window*", 0.9, (0.45, 0.75)),
    ("cityhub/textures/chblock*", 2.4, (-0.25, 0.6)), ("cityhub/textures/signtaxi*", 1.2, (0.5, 0.75)), ("cityhub/textures/*tv*.gif", 1.1, None),
    ("cityhub/textures/gladiatoons.gif", 1.1, None), ("cityhub/textures/marvinwash.gif", 1.1, None),
]

# ---- Planet X, where the doors between hubs lead: one small model far below all four hubs' levels. Exported where it sits
# in the Taz hub; look.c shifts the additions to the hub it is entered from.
PLANET_RULES = [
    ("resTex/shadowsub", "hide"), ("tazhub/textures/spacestation", "dome"), ("tazhub/textures/safarigrill01", "dome"),
    ("tazhub/textures/planetxgrass", "ground"),
    ("tazhub/extras/*hubxdoor", "gameplay"), ("tazhub/extras/metaledges", "gameplay"), ("tazhub/extras/tazcage?*", "gameplay"),
    ("tazhub/extras/safwarmwood*", "gameplay"), ("tazhub/textures/safwarmwood", "gameplay"), ("tazhub/extras/snowbeam*", "gameplay"),
    ("tazhub/extras/spookystake05", "gameplay"), ("tazhub/textures/planetflag", "gameplay"), ("tazhub/textures/chrome", "gameplay"),
]
PLANET_DETAIL = [("tazhub/textures/planetx?", "d_rock"), ("tazhub/textures/planetx", "d_rock"), ("tazhub/extras/aquasandcas2", "d_metal"), ("tazhub/extras/tazcage", "d_metal")]
PLANET_TILES = {
    "d_rock": dict(set="rock061", period=2.4, px=1024, detail=0.6, triplanar=True, rough=0.8, normal=0.9),
    "d_metal": dict(set="asphalt", period=1.2, px=1024, detail=0.1, triplanar=True, rough=0.32, normal=0.2),
    "red_ground": dict(set="rock061", period=1.8, px=2048, sat=1.0, val=1.0, tint=(1.9, 0.2, 0.14), rough=0.86),
}
PLANET_HAND = {
    "camera_B": dict(loc=(19.5, -3.0, -703.2), look_at=(16.5, 1.4, -705.0), lens=16.0),
    "camera_C": dict(loc=(13.0, 6.0, -703.5), look_at=(17.0, 1.0, -705.0), lens=16.0),
    "taz_offset_B": (0.0, 0.0, 0.0), "elephant_offset_B": (0.0, 0.0, 0.0),
}
PLANET_LOOK = dict(
    sun=dict(sun_azimuth=215.0, sun_elevation=48.0, sun_strength=2.26, sun_color="#fff1e0"),
    grade=dict(exposure=0.454, look="AgX - Punchy", saturation=1.3, bloom=0.5, fog=0.01, fog_start=400.0, fog_depth=400.0, ambient_strength=1.0),
    sky=dict(zenith="#070a24", horizon="#141a48", horizon_warm="#1c2258", sky_strength=1.0, cloud_white=0.2, ambient="#a29fb0"), cliff=dict(),
)

# Where the game paints its planets on the three space panels (1024 px): centre, radius, atmosphere. Read by space.py.
_BLUE = (0.07, 0.32, 1.0)
PLANET_SPACE = {
    "space01": [dict(c=(666, 458), r=141, atm=_BLUE, reach=1.34, paint=1.42), dict(c=(778, 573), r=55, atm=_BLUE, reach=1.3, paint=1.26, freq=5),
                dict(c=(444, 253), r=31, atm=_BLUE, reach=1.45, paint=1.42, freq=6)],
    "space02": [dict(c=(221, 228), r=70, atm=(1, 0.08, 0.05), reach=1.22, paint=1.2), dict(c=(131, 306), r=26, paint=1.16, freq=7),
                dict(c=(311, 203), r=9, atm=(0.05, 0.25, 1), reach=1.6, paint=1.5), dict(c=(608, 653), r=52, atm=(0.2, 1, 0.05), reach=1.32, paint=1.3),
                dict(c=(682, 573), r=21, atm=(0.05, 0.5, 0.05), reach=1.3, paint=1.2)],
    "space03": [dict(c=(577, 356), r=143, atm=_BLUE, reach=1.42, paint=1.42, gloss=0.3), dict(c=(790, 507), r=44, paint=1.12, freq=6)],
}

# ---- ice dome (scene 4): a Christmas shop frozen inside a dome. Its snow is painted white with blue zigzag edges.
ICE_RULES = [
    ("resobjs/*", "gameplay"), ("icedome/extras/*", "gameplay"), ("icedome/textures/tazbook*", "gameplay"),
    ("icedome/textures/tazwanted", "gameplay"), ("icedome/textures/tazanted02", "gameplay"), ("icedome/textures/icetreetaz*", "gameplay"),
    ("icedome/textures/sign*", "gameplay"), ("icedome/textures/xmaspressie*", "gameplay"), ("icedome/textures/cheesemouse*", "gameplay"),
    ("icedome/textures/snowboard*", "gameplay"), ("icedome/textures/electricfencesign", "gameplay"),
    ("icedome/skybox/*", "sky"), ("resTex/shadowsub", "hide"),
    ("icedome/textures/snowturf*", "snow"), ("icedome/textures/snowpud*", "snow"), ("icedome/textures/snowtile", "snow"),
    ("icedome/textures/snowdecal*", "snow"), ("icedome/textures/snowfoot*", "snow"),
]
ICE_DETAIL = [
    ("icedome/textures/icecubed*", "d_ice"), ("icedome/textures/igloo*", "d_ice"), ("icedome/textures/sdomestrip*", "d_ice"),
    ("icedome/textures/snowxmas*", "d_ice"), ("icedome/textures/bluetree*", "d_ice"), ("icedome/textures/purptree*", "d_ice"),
    ("icedome/textures/snowtree", "d_ice"), ("icedome/textures/frozentreats*", "d_ice"), ("icedome/textures/snowplant*", "d_ice"),
    ("icedome/textures/snowbeam*", "d_stone"), ("icedome/textures/palmbark", "d_stone"), ("icedome/textures/trunk*", "d_stone"),
]
ICE_TILES = dict(
    snowfield=dict(made="snow", period=3.2, px=1024, triplanar=True, rough=0.55, normal=0.8),
    d_ice=ZOO_TILES["d_ice"], d_stone=ZOO_TILES["d_stone"],
)
ICE_HAND = {
    "camera_B": dict(loc=(0.0, -20.0, -4.0), look_at=(0.0, 0.0, -8.0), lens=16.0),
    "camera_C": dict(loc=(20.0, 0.0, -4.0), look_at=(0.0, 0.0, -8.0), lens=16.0),
    "taz_offset_B": (0.0, 0.0, 0.0), "elephant_offset_B": (0.0, 0.0, 0.0),
}
ICE_LOOK = dict(
    sun=dict(sun_azimuth=62.0, sun_elevation=52.0, sun_strength=3.5, sun_color="#fff4e6"),
    grade=dict(exposure=0.2, look="AgX - Punchy", saturation=1.3, bloom=0.3, fog=0.05, fog_start=70.0, fog_depth=320.0, ambient_strength=1.05),
    sky=dict(zenith="#3f8fe8", horizon="#cfeaff", horizon_warm="#f2f8ff", sky_strength=1.2, cloud_white=1.2, ambient="#c7dfff"), cliff=dict(),
)

# ---- safari (scene 5): jungle islands in a river, a hot bright day. Same grass, dirt and water as the zoo hub.
SAFARI_RULES = [
    ("resobjs/*", "gameplay"), ("safari/extras/*", "gameplay"), ("safari/textures/tazbook*", "gameplay"), ("safari/textures/tazwanted", "gameplay"),
    ("safari/textures/tazanted02", "gameplay"), ("safari/textures/*crate*", "gameplay"), ("safari/textures/sign*", "gameplay"),
    ("safari/textures/safsign*", "gameplay"), ("safari/textures/samdoor*", "gameplay"), ("safari/textures/samgates*", "gameplay"),
    ("safari/textures/trunkwanted", "gameplay"), ("safari/textures/monkeytyre", "gameplay"), ("safari/textures/safhelipad", "gameplay"),
    ("safari/skybox/*", "sky"), ("resTex/shadowsub", "hide"), ("safari/textures/safariwater", "water"),
    ("safari/textures/pestsaf01", "lawn"), ("safari/textures/pestsaf02", "lawn"), ("safari/textures/tazfern02", "lawn"), ("safari/textures/tazfern06", "lawn"),
    ("safari/textures/pestsaf03", "ground"), ("safari/textures/pestsaf06", "ground"), ("safari/textures/pestsaf07", "ground"),
    ("safari/textures/grassedge*", "ground"), ("safari/textures/grassjoiner*", "ground"),
]
SAFARI_DETAIL = [
    ("safari/textures/safrock*", "d_rock"), ("safari/textures/sharprock*", "d_rock"), ("safari/textures/cagewall", "d_rock"),
    ("safari/textures/safaritemple*", "d_stone"), ("safari/textures/safwall*", "d_stone"), ("safari/textures/bunker*", "d_stone"),
    ("safari/textures/electricfencewall*", "d_stone"), ("safari/textures/guardtower*", "d_stone"), ("safari/textures/bridgepiller", "d_stone"),
    ("safari/textures/trunk*", "d_bark"), ("safari/textures/safwarmwood*", "d_bark"), ("safari/textures/tazwood*", "d_bark"),
    ("safari/textures/treeinternal", "d_bark"), ("safari/textures/palmbark", "d_bark"), ("safari/textures/hutwood", "d_bark"),
]
SAFARI_TILES = dict(d_rock=dict(ZOO_TILES["d_rock"], detail=0.38), d_stone=dict(ZOO_TILES["d_stone"], detail=0.45),
                    d_bark=dict(set="bark", period=1.6, px=1024, detail=0.6, triplanar=True, rough=0.8))
SAFARI_HAND = {
    "camera_B": dict(loc=(0.0, -20.0, 2.0), look_at=(0.0, 0.0, -2.0), lens=16.0),
    "camera_C": dict(loc=(20.0, 0.0, 2.0), look_at=(0.0, 0.0, -2.0), lens=16.0),
    "taz_offset_B": (0.0, 0.0, 0.0), "elephant_offset_B": (0.0, 0.0, 0.0),
}
SAFARI_LOOK = dict(
    sun=dict(sun_azimuth=130.0, sun_elevation=48.0, sun_strength=5.2, sun_color="#ffedcf"),
    grade=dict(exposure=0.45, look="AgX - Punchy", saturation=1.28, bloom=0.4, fog=0.06, fog_start=50.0, fog_depth=240.0, ambient_strength=1.0),
    sky=dict(zenith="#1257e6", horizon="#8fd0ff", horizon_warm="#fff4e2", sky_strength=1.3, cloud_white=1.35, ambient="#cdd8ea"), cliff=dict(),
)

# ---- aquarium (scene 6): a beach and water park on islands in the sea, entered down a long slide.
AQUA_RULES = [
    ("resobjs/*", "gameplay"), ("aqua/extras/*", "gameplay"), ("aqua/textures/tazbook*", "gameplay"), ("aqua/textures/tazwanted", "gameplay"),
    ("aqua/textures/tazanted02", "gameplay"), ("aqua/textures/*crate*", "gameplay"), ("aqua/textures/treasurechest*", "gameplay"),
    ("aqua/textures/stopbarrier*", "gameplay"), ("aqua/textures/pyratesign", "gameplay"), ("aqua/textures/aquaarrow*", "gameplay"),
    ("aqua/textures/aquaslidesign", "gameplay"), ("aqua/textures/sign*", "gameplay"), ("aqua/textures/target*", "gameplay"),
    ("aqua/skybox/*", "sky"), ("resTex/shadowsub", "hide"), ("aqua/textures/safariwater", "water"),
]
AQUA_DETAIL = [
    ("aqua/textures/pestisand*", "d_sand"), ("aqua/textures/aquasandjoiner*", "d_sand"),
    ("aqua/textures/orangerock*", "d_rock"), ("aqua/textures/orangeyelle*", "d_rock"), ("aqua/textures/orangeextra*", "d_rock"),
    ("aqua/textures/orangesandbase*", "d_rock"), ("aqua/textures/aquasandcas*", "d_stone"), ("aqua/textures/aquaseawall*", "d_stone"),
    ("aqua/textures/lighthouse*", "d_stone"), ("aqua/textures/lifehut*", "d_stone"), ("aqua/textures/marbtiles*", "d_stone"),
    ("aqua/textures/pyrateship*", "d_bark"), ("aqua/textures/aquaplanks", "d_bark"), ("aqua/textures/aquadecking*", "d_bark"),
    ("aqua/textures/beachhut*", "d_bark"), ("aqua/textures/palmbark", "d_bark"), ("aqua/textures/woodblock*", "d_bark"),
    ("aqua/textures/slide*", "d_gloss"), ("aqua/textures/wastepipes*", "d_gloss"), ("aqua/textures/aquapoles*", "d_gloss"),
    ("aqua/textures/washcase*", "d_gloss"), ("aqua/textures/sinkedge", "d_gloss"),
]
AQUA_TILES = dict(d_rock=SAFARI_TILES["d_rock"], d_stone=SAFARI_TILES["d_stone"], d_bark=SAFARI_TILES["d_bark"],
                  d_sand=dict(made="sand", period=2.4, px=1024, detail=0.8, triplanar=True, rough=0.9, normal=0.7),
                  d_gloss=dict(made="smooth", period=4.0, px=64, detail=0.01, rough=0.16, normal=0.0))
AQUA_HAND = {
    "camera_B": dict(loc=(20.0, -20.0, -8.0), look_at=(30.0, 20.0, -14.0), lens=16.0),
    "camera_C": dict(loc=(60.0, 20.0, -8.0), look_at=(30.0, 20.0, -14.0), lens=16.0),
    "taz_offset_B": (0.0, 0.0, 0.0), "elephant_offset_B": (0.0, 0.0, 0.0),
}
AQUA_LOOK = dict(
    sun=dict(sun_azimuth=150.0, sun_elevation=55.0, sun_strength=5.0, sun_color="#fff2dc"),
    grade=dict(exposure=0.42, look="AgX - Punchy", saturation=1.28, bloom=0.4, fog=0.05, fog_start=70.0, fog_depth=340.0, ambient_strength=1.0),
    sky=dict(zenith="#1257e6", horizon="#8fd0ff", horizon_warm="#fff4e2", sky_strength=1.3, cloud_white=1.35, ambient="#dedad7"), cliff=dict(),
)

# ---- zoo boss (scene 7): elephant football on a clay pitch inside the zoo's walls, at sunset. Zoo hub brick, grass and trees.
ZOOBOSS_RULES = [
    ("resobjs/*", "gameplay"), ("zooboss/extras/*", "gameplay"), ("zooboss/textures/tazbook*", "gameplay"), ("zooboss/textures/tazwanted", "gameplay"),
    ("zooboss/textures/tazanted02", "gameplay"), ("zooboss/textures/zepp*", "gameplay"), ("zooboss/textures/sheild*", "gameplay"),
    ("zooboss/textures/truck*", "gameplay"), ("zooboss/textures/van*", "gameplay"), ("zooboss/textures/postbox*", "gameplay"),
    ("zooboss/textures/sign*", "gameplay"), ("zooboss/textures/safwheel*", "gameplay"),
    ("zooboss/skybox/*", "sky"), ("resTex/shadowsub", "hide"), ("zooboss/textures/safariwater", "water"),
    ("zooboss/textures/zoohubgrass*", "lawn"), ("zooboss/textures/hubflowers*", "lawn"), ("zooboss/textures/zoo_road", "lawn"),
    ("zooboss/textures/zoo_road05", "lawn"), ("zooboss/textures/zoo_road06", "lawn"),
    ("zooboss/textures/zoohubpath*", "ground"), ("zooboss/textures/zoohubbankedge", "ground"),
    ("zooboss/textures/tazwood02a", "tree"), ("zooboss/textures/tazfern05*", "tree"),
    ("zooboss/textures/zoohubwall2", "lit"), ("zooboss/textures/zoohubpiller*", "brick"), ("zooboss/textures/zoohubwall*", "brick"),
    ("zooboss/textures/tower", "brick"), ("zooboss/textures/tower0*", "brick"),
]
ZOOBOSS_DETAIL = [
    ("zooboss/textures/soccer_*", "d_sand"), ("zooboss/textures/zoo_citblock*", "d_stone"), ("zooboss/textures/safrock*", "d_rock"),
    ("zooboss/textures/sharprock*", "d_rock"), ("zooboss/textures/farm_plot*", "d_bark"), ("zooboss/textures/jhut*", "d_bark"),
]
ZOOBOSS_TILES = dict(d_sand=dict(AQUA_TILES["d_sand"], period=1.5, detail=0.35, normal=0.3), d_stone=SAFARI_TILES["d_stone"], d_rock=SAFARI_TILES["d_rock"], d_bark=SAFARI_TILES["d_bark"])
ZOOBOSS_HAND = {
    "camera_B": dict(loc=(0.0, -9.0, 3.0), look_at=(0.0, 8.0, 0.5), lens=16.0),
    "camera_C": dict(loc=(14.0, 0.0, 3.0), look_at=(0.0, 0.0, 0.5), lens=16.0),
    "taz_offset_B": (0.0, 0.0, 0.0), "elephant_offset_B": (0.0, 0.0, 0.0),
}
ZOOBOSS_LOOK = dict(
    sun=dict(sun_azimuth=230.0, sun_elevation=30.0, sun_strength=4.6, sun_color="#ffd2a0"),
    grade=dict(exposure=0.4, look="AgX - Punchy", saturation=1.25, bloom=0.45, fog=0.05, fog_start=60.0, fog_depth=320.0, ambient_strength=0.9),
    sky=dict(zenith="#c2301a", horizon="#ffb060", horizon_warm="#ffd890", sky_strength=1.0, cloud_white=1.0, ambient="#e0c0b4"), cliff=dict(),
)
# ---- the frontend (scene 1): the diorama behind the menus. Its flat poster colours are the point, so they are held.
FRONT_RULES = [
    ("resTex/shadowsub", "hide"), ("resobjs/*", "gameplay"), ("frontend/skybox/*", "sky"),
    ("frontend/textures/safariwater", "water"), ("frontend/textures/tazfern0[1289]*", "ground"), ("frontend/textures/path*", "ground"),
]
FRONT_HAND = {
    "camera_B": dict(loc=(-5.5, -7.2, -1.3), look_at=(4.0, 8.0, 0.0), lens=16.0),
    "camera_C": dict(loc=(20.0, 2.0, 2.0), look_at=(10.0, 16.0, 0.0), lens=16.0),
    "taz_offset_B": (0.0, 0.0, 0.0), "elephant_offset_B": (0.0, 0.0, 0.0),
}
FRONT_LOOK = dict(
    sun=dict(sun_azimuth=75.0, sun_elevation=42.0, sun_strength=2.25, sun_color="#fff0d6"),  # from the painted sun's side
    grade=dict(exposure=-0.134, look="AgX - Punchy", saturation=1.05, bloom=0.2, fog=0.01, fog_start=200.0, fog_depth=400.0, ambient_strength=1.0),
    sky=dict(zenith="#1257e6", horizon="#8fd0ff", horizon_warm="#fff4e2", sky_strength=1.3, cloud_white=1.0, ambient="#cdd8ea"), cliff=dict(),
)

# ---- department store (scene 9): a shop at night. Like the city, its colour is blue light baked over pale paint.
DEPT_RULES = [
    ("resobjs/*", "gameplay"), ("deptstr/extras/*", "gameplay"), ("deptstr/textures/tazbook*", "gameplay"), ("deptstr/textures/tazcage*", "gameplay"),
    ("deptstr/textures/tazwanted", "gameplay"), ("deptstr/textures/tazanted02", "gameplay"), ("deptstr/textures/bombbit*", "transient"),
    ("resTex/shadowsub", "hide"),
]
DEPT_HAND = {
    "camera_B": dict(loc=(20.0, 0.0, -10.0), look_at=(40.0, 10.0, -12.0), lens=16.0),
    "camera_C": dict(loc=(60.0, 0.0, -10.0), look_at=(40.0, 10.0, -12.0), lens=16.0),
    "taz_offset_B": (0.0, 0.0, 0.0), "elephant_offset_B": (0.0, 0.0, 0.0),
}
DEPT_LOOK = dict(
    sun=dict(sun_azimuth=242.0, sun_elevation=52.0, sun_strength=1.1, sun_color="#a9c0ff"),
    grade=dict(exposure=0.3, look="AgX - Punchy", saturation=1.2, bloom=0.4, fog=0.1, fog_start=80.0, fog_depth=300.0, ambient_strength=1.0),
    sky=CITY_LOOK["sky"], cliff=dict(),
)
DEPT_GLOW = [(f"deptstr/textures/{p}", g, r) for p, g, r in (
    ("*neon*", 2.0, None), ("winstar*", 1.6, (0.3, 0.6)), ("deptlight*", 0.45, (0.55, 0.8)), ("light.frame*", 2.2, (0.45, 0.7)), ("lightstrip", 1.6, (0.45, 0.7)),
    ("road_barrier_light*", 2.2, (0.4, 0.65)), ("racecarheadlight", 1.8, None), ("shoptvflash*", 0.9, None), ("tvsnow*", 0.8, None), ("tv0*", 0.8, None),
    ("littletv*", 0.8, None), ("blackholemonitors*", 0.8, None), ("scoreboardanim*", 1.3, None))]
# Paint kept, with a fine relief: glazed floor tile, painted plaster on the walls and fittings.
DEPT_DETAIL = [(f"deptstr/textures/{p}", m) for p, m in (
    ("ceramictile*", "d_tile"), ("shopblackfloor*", "d_tile"), ("citypave*", "d_tile"), ("leading*", "d_wall"), ("walljoiner*", "d_wall"), ("toywall*", "d_wall"),
    ("barsblue*", "d_wall"), ("shopbowl*", "d_wall"), ("shopbed*", "d_wall"), ("shopdanger*", "d_wall"), ("racetrak*", "d_wall"), ("sportsnfl*", "d_wall"),
    ("pestmart*", "d_wall"), ("toybricks", "d_wall"), ("toycastle*", "d_wall"), ("shopdough*", "d_wall"))]
DEPT_TILES = {
    "d_tile": dict(set="paving", period=2.2, px=1024, detail=0.14, triplanar=True, rough=0.34, normal=0.22),
    "d_wall": dict(set="old_sandstone", period=2.6, px=1024, detail=0.22, triplanar=True, rough=0.72, normal=0.4),
}


def room_lamps(rooms, height, radius, color, power):
    """Indoor light: rows of ceiling lamps over each room (game x0, z0, x1, z1, floor y, columns, rows), as `extra` lamps.
    Lamps ignore floors, and a grid cell keeps its four nearest, so don't stack rooms' lamps over each other."""
    out = []
    for x0, z0, x1, z1, floor, nx, nz in rooms:
        for i in range(nx):
            for k in range(nz):
                out.append(((x0 + (x1 - x0) * (i + 0.5) / nx) / 250, (z0 + (z1 - z0) * (k + 0.5) / nz) / 250, (floor + height) / 250, radius, color, power))
    return tuple(out)


DEPT_ROOMS = (
    (-11800, -5200, 1000, 6200, -2800, 4, 4), (-10500, 4200, 1000, 6400, -300, 3, 1),  # main hall and its balcony
    (-1000, -6000, 10000, 8000, -800, 3, 4),    # the upper floor: start, toys
    (12500, -3500, 19500, 7000, -1300, 2, 3),   # round room
    (20000, 500, 40000, 4500, -1300, 5, 1),     # long gallery
    (-22000, -6000, -14000, 7000, -2800, 2, 3), # sports arena
    (-12000, 6600, 1500, 12500, -2800, 3, 1),   # back of the hall
    (2000, -8600, 11000, -6800, -1800, 3, 1), (12500, -6200, 17500, -4600, -1800, 2, 1),  # service street
)
DEPT_LAMPS = dict(color="#ffd9a8", power=0.0, radius=13.0, drop=0.7, cone=0.8, pool_power=0.0, pool_radius=8.0, pool_height=3.2, pool_cone=-0.2,
                  extra=room_lamps(DEPT_ROOMS, 1700, 13.0, "#ffd9a8", 2.1))

# ---- museum (scene 10): the same night treatment and indoor recipe as the store, on three floors (100, 1900, 5000).
MUSE_RULES = [
    ("resobjs/*", "gameplay"), ("museum/extras/*", "gameplay"), ("museum/textures/tazbook*", "gameplay"), ("museum/textures/tazcage*", "gameplay"),
    ("museum/textures/tazwanted", "gameplay"), ("museum/textures/tazanted02", "gameplay"), ("museum/textures/bombbit*", "transient"), ("resTex/shadowsub", "hide"),
]
MUSE_GLOW = [(f"museum/textures/{p}", g, r) for p, g, r in (
    ("tvmuseum*", 0.8, None), ("tvsnow*", 0.8, None), ("tv", 0.8, None), ("compmont*", 0.7, None), ("light.frame*", 2.2, (0.45, 0.7)), ("lightbulbflashing*", 1.2, (0.5, 0.8)),
    ("uplights", 1.2, (0.45, 0.7)), ("labtanklight", 1.8, None), ("lightstrip", 1.6, (0.45, 0.7)), ("window*", 0.5, (0.5, 0.8)),
    ("removal_truck_lights", 1.8, None))]
MUSE_DETAIL = [(f"museum/textures/{p}", m) for p, m in (
    ("marbtiles*", "d_tile"), ("modfloor*", "d_tile"), ("woodfloor*", "d_tile"), ("ancientfloor*", "d_tile"), ("industfloor*", "d_tile"), ("haringfloor*", "d_tile"),
    ("floorsteel*", "d_tile"), ("*carpet*", "d_wall"), ("marbwall*", "d_wall"), ("lightbluewall*", "d_wall"), ("yellowwall*", "d_wall"), ("modwall*", "d_wall"),
    ("wall*", "d_wall"), ("pillar*", "d_wall"), ("fineartmarb*", "d_wall"), ("industwalls*", "d_wall"), ("industmarb*", "d_wall"), ("libarywall*", "d_wall"),
    ("tornwallpaper*", "d_wall"), ("newmoneywall*", "d_wall"), ("roofpanels*", "d_wall"))]
MUSE_ROOMS = (
    (-15000, -8000, -11500, 1000, 100, 1, 3), (-11500, -8000, -3000, -5000, 100, 3, 1), (-10500, -2000, -6500, 1500, 100, 1, 1),  # west ring, octagon
    (-13500, -4700, -9500, -2000, 100, 1, 1), (-7000, 1500, -5000, 4500, 100, 1, 1), (-5000, 5000, -3000, 9000, 100, 1, 1), (-4000, -9000, -1000, -5000, 100, 1, 1),
    (1000, -13000, 5000, -2500, 1900, 1, 3), (-2000, 1000, 4000, 5000, 1900, 2, 1), (5000, -3500, 8000, -500, 1900, 1, 1), (6000, 2000, 9500, 6000, 1900, 1, 1),  # middle floor
    (12500, -6000, 16500, 7000, 1900, 1, 3), (5000, -11000, 9500, -8000, 1900, 1, 1), (5000, 6500, 8000, 10000, 1900, 1, 1),
    (-6000, 0, -500, 4000, 5000, 2, 1), (-1000, 2000, 2500, 5000, 5000, 1, 1), (3000, 0, 5500, 6000, 5000, 1, 2), (6000, 2000, 9500, 6000, 5000, 1, 1),  # top floor
    (2000, 8000, 7000, 16000, 5000, 1, 2), (12500, -3000, 16500, 8000, 5000, 1, 3), (1000, -8000, 5000, -3000, 5000, 1, 1), (5000, -7500, 16000, -5000, 5000, 2, 1),
)
MUSE_LAMPS = dict(DEPT_LAMPS, extra=room_lamps(MUSE_ROOMS, 1400, 13.0, "#ffd9a8", 1.8))
MUSE_HAND = dict(DEPT_HAND, camera_B=dict(loc=(12.0, -40.0, 11.0), look_at=(12.0, -20.0, 8.0), lens=16.0), camera_C=dict(loc=(-40.0, -20.0, 3.0), look_at=(-30.0, -5.0, 1.0), lens=16.0))

# ---- construction site (scene 11): outdoors at night, the city hub's moon and lamps on a tower of steel floors.
CONS_RULES = [
    ("resobjs/*", "gameplay"), ("contruct/extras/*", "gameplay"), ("contruct/textures/tazbook*", "gameplay"), ("contruct/textures/tazcage*", "gameplay"),
    ("contruct/textures/tazwanted", "gameplay"), ("contruct/textures/tazanted02", "gameplay"), ("contruct/textures/bombbit*", "transient"),
    ("contruct/textures/postlamp", "lamp"), ("resTex/shadowsub", "hide"),
]
CONS_GLOW = [(f"contruct/textures/{p}", g, r) for p, g, r in (
    ("signgreen*", 1.6, None), ("signred*", 1.6, None), ("contubesigns*", 1.4, (0.3, 0.6)), ("contowersign", 1.2, (0.4, 0.7)), ("conexitsign*", 1.2, (0.4, 0.7)), ("esign_*", 1.2, (0.4, 0.7)),
    ("trafficlight*", 1.8, (0.4, 0.7)), ("beacon_lamp", 2.2, (0.4, 0.7)), ("latern_light", 2.2, (0.4, 0.7)), ("cblight", 2.0, (0.4, 0.7)), ("digger_lamp", 1.8, (0.4, 0.7)), ("window01", 0.9, (0.45, 0.75)))]
CONS_DETAIL = [(f"contruct/textures/{p}", m) for p, m in (
    ("ground*", "d_conc"), ("concrete*", "d_conc"), ("greyconcrete*", "d_conc"), ("woodplanks*", "d_wall"), ("workhutwall*", "d_wall"),
    ("gurder*", "d_steel"), ("c_metal*", "d_steel"), ("digger_metal*", "d_steel"), ("oilbarrel*", "d_steel"), ("const_barrel*", "d_steel"), ("skip*", "d_steel"), ("ironrods*", "d_steel"))]
CONS_TILES = {
    "d_conc": dict(set="paving", period=3.0, px=1024, detail=0.35, triplanar=True, rough=0.85, normal=0.6),
    "d_wall": DEPT_TILES["d_wall"],
    "d_steel": dict(set="asphalt", period=1.2, px=1024, detail=0.12, triplanar=True, rough=0.4, normal=0.25),
}
CONS_LOOK = dict(CITY_LOOK, grade=dict(CITY_LOOK["grade"], ambient_strength=0.72))  # the tower's floors have no lamps of their own
CONS_HAND = dict(DEPT_HAND, camera_B=dict(loc=(0.0, -40.0, -46.0), look_at=(0.0, 0.0, -40.0), lens=16.0), camera_C=dict(loc=(-30.0, 20.0, 14.0), look_at=(0.0, 10.0, 12.0), lens=16.0))

# ---- city boss (scene 12): a lit TV arena. Its colour is painted into the vertices, so it is kept (no unbake) and held through the tone curve.
BOSS_RULES = [("resobjs/*", "gameplay"), ("cityboss/extras/*", "gameplay"), ("resTex/shadowsub", "hide")]
BOSS_GLOW = [(f"cityboss/textures/{p}", g, r) for p, g, r in (
    ("scoreboardanim*", 1.3, None), ("stadedgeani*", 0.9, None), ("trafficlights*", 1.6, (0.4, 0.7)), ("lightcolours", 1.4, None), ("podlights", 1.4, None),
    ("cbfloodlights*", 1.8, (0.45, 0.75)), ("cbfloorlights", 1.2, (0.4, 0.7)), ("greenlight", 1.6, None), ("redlight", 1.6, None), ("yellowlight", 1.6, None), ("truck_headlights*", 1.6, (0.4, 0.7)))]
BOSS_DETAIL = [(f"cityboss/textures/{p}", m) for p, m in (
    ("cbfloor", "d_tile"), ("cbfloorspecial", "d_tile"), ("magfloor*", "d_tile"), ("stadwall*", "d_wall"), ("stadstairs*", "d_wall"), ("stadtunnel*", "d_wall"),
    ("cbtunnel*", "d_wall"), ("seats*", "d_wall"), ("stadseats*", "d_wall"), ("billboardedges", "d_wall"), ("tunneledges", "d_wall"))]
BOSS_LOOK = dict(
    sun=dict(sun_azimuth=75.0, sun_elevation=62.0, sun_strength=1.62, sun_color="#fff0d6"),
    grade=dict(exposure=-0.134, look="AgX - Punchy", saturation=1.08, bloom=0.3, fog=0.01, fog_start=200.0, fog_depth=400.0, ambient_strength=0.68),
    sky=dict(zenith="#1257e6", horizon="#8fd0ff", horizon_warm="#fff4e2", sky_strength=1.3, cloud_white=1.0, ambient="#cdd8ea"), cliff=dict(),
)
BOSS_HAND = dict(DEPT_HAND, camera_B=dict(loc=(0.0, -20.0, -2.0), look_at=(0.0, 10.0, -7.0), lens=16.0), camera_C=dict(loc=(20.0, 0.0, -2.0), look_at=(-5.0, 0.0, -7.0), lens=16.0))

# ---- west hub (scene 13): a sunlit desert canyon. WEST_TILES and WEST_LOOK are the base for the other Wild West levels.
WEST_RULES = [
    ("resobjs/*", "gameplay"), ("westhub/extras/*", "gameplay"), ("westhub/textures/westcube*", "gameplay"), ("westhub/textures/exp_*", "gameplay"),
    ("westhub/textures/crateside*", "gameplay"), ("westhub/textures/tnt", "gameplay"), ("westhub/textures/dynamite*", "gameplay"),
    ("westhub/textures/*sign*", "gameplay"), ("westhub/textures/warning*", "gameplay"), ("westhub/textures/arrowbend", "gameplay"),
    ("westhub/textures/roadnarrows", "gameplay"), ("westhub/textures/barrier*", "gameplay"), ("westhub/textures/train_barrier*", "gameplay"),
    ("westhub/textures/train_waring_sign", "gameplay"), ("westhub/textures/tazshapedhole*", "gameplay"), ("westhub/textures/tumble", "gameplay"),
    ("westhub/skybox/*", "sky"), ("resTex/shadowsub", "hide"), ("westhub/textures/sand", "ground"), ("westhub/textures/sandrock*", "ground"),
]
WEST_DETAIL = [(f"westhub/textures/{p}", m) for p, m in (
    ("vert_strips*", "d_canyon"), ("wwrock*", "d_canyon"), ("wwsml*", "d_canyon"), ("wwroad", "d_road"), ("roadstart", "d_road"),
    ("sleeper", "d_plank"), ("track_wood", "d_plank"), ("mine_wood*", "d_plank"), ("spookhouse_wood", "d_plank"), ("spookhouse_side*", "d_plank"),
    ("spookhouse_newroof*", "d_plank"), ("spookhouse_roof_tile", "d_plank"), ("station_side*", "d_plank"), ("station_backside", "d_plank"),
    ("station_floor", "d_plank"), ("station_stair*", "d_plank"), ("station_roof*", "d_plank"), ("hut_*", "d_plank"), ("teepee_wood", "d_plank"),
    ("ammodump_woodbase*", "d_plank"), ("ammo_dump_*wall*", "d_plank"), ("totem*", "d_plank"),
    ("train0*", "d_iron"), ("train1*", "d_iron"), ("train2*", "d_iron"), ("train3*", "d_iron"), ("track", "d_iron"), ("kannon*", "d_iron"), ("bearing*", "d_iron"))]
WEST_TILES = dict(
    d_sand=dict(made="sand", period=2.6, px=1024, detail=0.7, triplanar=True, rough=0.92, normal=0.65),
    d_canyon=dict(set="old_sandstone", period=4.2, px=1024, detail=0.55, triplanar=True, rough=0.88, normal=0.9),
    d_road=dict(set="asphalt", period=3.0, px=1024, detail=0.3, triplanar=True, rough=0.85, normal=0.5),
    d_plank=dict(set="bark", period=1.6, px=1024, detail=0.45, triplanar=True, rough=0.78, normal=0.7),
    d_iron=dict(set="asphalt", period=1.2, px=1024, detail=0.1, triplanar=True, rough=0.38, normal=0.2),
)
WEST_HAND = dict(DEPT_HAND, camera_B=dict(loc=(10.0, 40.0, 16.0), look_at=(20.0, 60.0, 14.0), lens=16.0), camera_C=dict(loc=(-20.0, 10.0, 16.0), look_at=(10.0, 30.0, 14.0), lens=16.0))
WEST_LOOK = dict(
    sun=dict(sun_azimuth=250.0, sun_elevation=52.0, sun_strength=5.0, sun_color="#fff0d8"),
    grade=dict(exposure=0.26, look="AgX - Punchy", saturation=1.25, bloom=0.35, fog=0.05, fog_start=80.0, fog_depth=380.0, ambient_strength=1.22),
    sky=dict(zenith="#1a68e0", horizon="#a6dcff", horizon_warm="#ffe9c8", sky_strength=1.3, cloud_white=1.3, ambient="#e8d8cc"), cliff=dict(),
)

LEVELS = {
    "zoohub": dict(scene=3, pak="zoohub", blend="zoohub.blend", out="pass5", captures=("world-hero.bin", "world-sweep.bin"), rules=ZOO_RULES, hand=ZOO_HAND, look=ZOO_LOOK,
                   hdri=ZOO_HDRI, hdri_rotation=0.0, hub=(-31.5, -31.5, 18.5, 19.5), dress_characters=True,
                   tiles=ZOO_TILES, detail=ZOO_DETAIL, skin=dict(tile=520.0, grain=0.18),
                   binds={"ground": (("lawn", 0, 0.0, 1.0), ("dirt", 1, -0.14, -0.05))},
                   flats={"steel": ((0.20, 0.17, 0.15), 0.4), "link": ((0.62, 0.68, 0.74), 0.35), "iron": ((0.045, 0.045, 0.05), 0.4)},
                   wire="zoohub/textures/barbed_wire", chain="zoohub/textures/chain", grill="zoohub/textures/safarigrill01",
                   solids=dict(cards={t: dict(mat="iron", size=(560.0, 1128.0), depth=5.0, tol=1.2, area=25.0)
                                      for t in ("zoohub/textures/gate", "zoohub/textures/zoohubgate")},
                               soft=("zoohub/textures/dinghy2", "zoohub/textures/lilo3"))),
    "cityhub": dict(scene=8, pak="cityhub", blend="city/cityhub.blend", out="city/pass1", rules=CITY_RULES, hand=CITY_HAND,
                    look=CITY_LOOK, hdri=None, hdri_rotation=0.0, hub=(-66.0, -50.0, 72.0, 82.0), sky_panels=True, clutter=False,
                    materials=("lawn", "asphalt", "paving", "paint", "grass", "flat", "flat_wind", "bark", "leaf_core", "leaves", "link"),
                    flats={"link": ((0.42, 0.44, 0.5), 0.4)},
                    captures=("city/world-hero.bin", "city/world-sweep.bin", "city/world-sweep-a.bin", "city/world-sweep-b.bin"),
                    solids=dict(cards={"cityhub/textures/safarigrill01": dict(size=(90.0, 345.0), depth=4.5, tol=1.4, area=30.0, repeat=2, each_draw=True,
                                                                              tint=(2.1, 1.9, 1.35)),
                                       "cityhub/textures/chain2": dict(mat="link", links=True)}, soft=()),
                    trees=("cityhub/textures/tazwood02a", "cityhub/textures/tazfern05*"), fog_color="#20366f",
                    tints={"leaves": (2.0, 2.4, 1.6), "leaf_core": (2.0, 2.4, 1.6), "bark": (2.4, 1.8, 1.5)},  # readable under moonlight
                    tiles={"asphalt": dict(period=4.0, px=2048, sat=0.75, val=1.2, tint=(0.82, 0.86, 0.95), rough=0.75),
                           "paving": dict(period=4.5, px=2048, sat=0.55, val=1.35, tint=(0.95, 0.96, 1.0), rough=0.82)},
                    binds={"ground": (("paving", 1, -0.14, -0.05),),
                           "lawn": (("lawn", 0, 0.0, 1.0),),
                           "road": (("asphalt", 3, 0.42, 0.56), ("paint", 3, 0.86, 0.93))},
                    glow=CITY_GLOW, lamps=CITY_LAMPS, unbake=0.5, sky_gain=2.4, char_fill=(0.24, 0.26, 0.32)),
    "planetx": dict(scene=30, pak=("tazhub", "cityhub"),  # the city has its own copies of three door paintings
                    blend="planet/planetx.blend", out="planet/pass2", rules=PLANET_RULES, hand=PLANET_HAND, look=PLANET_LOOK,
                    hdri=None, hdri_rotation=0.0, hub=(11.2, -3.9, 21.8, 6.8), clutter=False, game_sky=True, clear_islands=True,
                    materials=tuple(PLANET_TILES) + ("lawn", "grass"), tiles=PLANET_TILES, detail=PLANET_DETAIL,
                    tints={"lawn": (0.16, 1.45, 0.4), "red_ground": (1.45, 1.2, 1.2)}, binds={"ground": (("lawn", 0, 0.0, 1.0), ("red_ground", 1, -0.14, -0.05))},
                    grass_opts=dict(height=(0.09, 0.22), flowers=0.0, weeds=0.0), dome="dome", space=PLANET_SPACE, flats={"hull": ((3.2, 3.2, 3.25), 0.42)}, hold=1.0, contrast=1.0, bloom_threshold=25.0, char_fill=(0.16, 0.16, 0.22)),
    "icedome": dict(scene=4, pak="icedome", blend="zoo-levels/icedome/icedome.blend", out="zoo-levels/icedome/pass1", rules=ICE_RULES, hand=ICE_HAND,
                    look=ICE_LOOK, hdri=None, hdri_rotation=0.0, hub=(-71.0, -58.0, 71.0, 50.0), sky_panels=True, clutter=False,
                    captures=("zoo-levels/icedome/world-hero.bin", "zoo-levels/icedome/world-sweep-a.bin", "zoo-levels/icedome/world-sweep-b.bin"),
                    materials=tuple(ICE_TILES) + ("flat",), tiles=ICE_TILES, detail=ICE_DETAIL, fog_color="#cfe6fb",
                    binds={"snow": (("d_ice", 4, -1.0, 0.0), ("snowfield", 3, 0.66, 0.82))},
                    lumps=dict(roles=("snow",), density=0.2, colour="#f4f9ff"), island_boxes=True, sky_gain=1.35, night_sky=False, ground_tint=(0.74, 0.67, 0.59), tints={"snowfield": (0.88, 0.9, 0.94)}),
    "safari": dict(scene=5, pak="safari", blend="zoo-levels/safari/safari.blend", out="zoo-levels/safari/pass1", rules=SAFARI_RULES, hand=SAFARI_HAND,
                   look=SAFARI_LOOK, hdri=None, hdri_rotation=0.0, hub=(-79.0, -64.0, 71.0, 80.0), sky_panels=True, night_sky=False, grass_density=30.0, island_boxes=True,
                   captures=("zoo-levels/safari/world-hero.bin", "zoo-levels/safari/world-sweep-a.bin", "zoo-levels/safari/world-sweep-b.bin"),
                   materials=tuple(SAFARI_TILES) + ("lawn", "dirt", "grass", "flat", "flat_wind", "water", "water_bed", "foam"), tiles=SAFARI_TILES,
                   detail=SAFARI_DETAIL, binds={"ground": (("lawn", 0, 0.0, 1.0), ("dirt", 1, -0.14, -0.05))}, sky_gain=1.3),
    "aqua": dict(scene=6, pak="aqua", blend="zoo-levels/aqua/aqua.blend", out="zoo-levels/aqua/pass1", rules=AQUA_RULES, hand=AQUA_HAND,
                 look=AQUA_LOOK, hdri=None, hdri_rotation=0.0, hub=(-96.0, -79.0, 116.0, 127.0), sky_panels=True, night_sky=False, clutter=False, island_boxes=True,
                 captures=("zoo-levels/aqua/world-hero.bin", "zoo-levels/aqua/world-sweep-a.bin", "zoo-levels/aqua/world-sweep-b.bin"),
                 materials=tuple(AQUA_TILES) + ("dirt", "water", "water_bed"), tiles=AQUA_TILES, detail=AQUA_DETAIL, sky_gain=1.3, foam=0, water_walls=False, ground_tint=(0.69, 0.6, 0.47)),
    "zooboss": dict(scene=7, pak="zooboss", blend="zoo-levels/zooboss/zooboss.blend", out="zoo-levels/zooboss/pass1", rules=ZOOBOSS_RULES, hand=ZOOBOSS_HAND,
                    look=ZOOBOSS_LOOK, hdri=None, hdri_rotation=0.0, hub=(-30.0, -30.0, 30.0, 27.0), sky_panels=True, night_sky=False, clutter=False,
                    island_boxes=True, grass_density=40.0, skin=dict(tile=520.0, grain=0.18), char_keep=0.8, fog_color="#ffc090", ground_tint=(0.72, 0.6, 0.5), sky_gain=1.25,
                    captures=("zoo-levels/zooboss/world-hero.bin", "zoo-levels/zooboss/world-sweep-a.bin", "zoo-levels/zooboss/world-sweep-b.bin"),
                    materials=tuple(ZOOBOSS_TILES) + ("lawn", "dirt", "brick", "trim", "bark", "leaves", "leaf_core", "grass", "flat", "flat_wind", "water", "water_bed", "foam", "skin"),
                    tiles=ZOOBOSS_TILES, detail=ZOOBOSS_DETAIL, binds={"ground": (("lawn", 0, 0.0, 1.0), ("dirt", 1, -0.14, -0.05))}),
    "frontend": dict(scene=1, pak="frontend", blend="screens/capture/frontend.blend", out="screens/pass1", rules=FRONT_RULES, hand=FRONT_HAND,
                     look=FRONT_LOOK, hdri=None, hdri_rotation=0.0, hub=(-25.0, -10.0, 62.0, 42.0), clutter=False, game_sky=True,
                     captures=("screens/capture/world-sweep.bin",), materials=("lawn", "dirt", "grass", "flat", "flat_wind", "water", "water_bed", "foam"),
                     binds={"ground": (("lawn", 0, 0.0, 1.0), ("dirt", 1, -0.14, -0.05))}, grass_opts=dict(height=(0.08, 0.2), flowers=0.0, weeds=0.0), grass_min=0.7, tints={"dirt": (1.75, 1.2, 0.62)},
                     hold=1.0, contrast=1.0, bloom_threshold=3.0, char_fill=(0.12, 0.12, 0.14)),
    "deptstr": dict(scene=9, pak="deptstr", blend="city-levels/deptstr/deptstr.blend", out="city-levels/deptstr/pass1", rules=DEPT_RULES, hand=DEPT_HAND,
                    look=DEPT_LOOK, hdri=None, hdri_rotation=0.0, hub=(-90.0, -44.0, 162.0, 53.0), game_sky=True, clutter=False,
                    materials=tuple(DEPT_TILES) + ("flat",), tiles=DEPT_TILES, detail=DEPT_DETAIL, tints={"d_tile": (1.5, 1.5, 1.58)}, captures=("city-levels/deptstr/world-hero.bin", "city-levels/deptstr/world-sweep.bin"),
                    fog_color="#20366f", glow=DEPT_GLOW, lamps=DEPT_LAMPS, unbake=0.5, sky_gain=2.4, char_fill=(0.24, 0.26, 0.32)),
    "museum": dict(scene=10, pak="museum", blend="city-levels/museum/museum.blend", out="city-levels/museum/pass1", rules=MUSE_RULES, hand=MUSE_HAND,
                   look=DEPT_LOOK, hdri=None, hdri_rotation=0.0, hub=(-79.0, -68.0, 79.0, 68.0), game_sky=True, clutter=False,
                   materials=tuple(DEPT_TILES) + ("flat",), tiles=DEPT_TILES, detail=MUSE_DETAIL, tints={"d_tile": (1.5, 1.5, 1.58)},
                   captures=("city-levels/museum/world-hero.bin",), fog_color="#20366f", glow=MUSE_GLOW, lamps=MUSE_LAMPS, unbake=0.5, sky_gain=2.4, char_fill=(0.24, 0.26, 0.32)),
    "contruct": dict(scene=11, pak="contruct", blend="city-levels/contruct/contruct.blend", out="city-levels/contruct/pass1", rules=CONS_RULES, hand=CONS_HAND,
                     look=CONS_LOOK, hdri=None, hdri_rotation=0.0, hub=(-121.0, -108.0, 105.0, 68.0), game_sky=True, clutter=False,
                     materials=tuple(CONS_TILES) + ("flat",), tiles=CONS_TILES, detail=CONS_DETAIL, tints={"d_conc": (1.25, 1.25, 1.35)}, captures=("city-levels/contruct/world-hero.bin",),
                     fog_color="#20366f", glow=CONS_GLOW, lamps=dict(CITY_LAMPS, power=1.7, cone=0.35, pool_power=0.45, extra=()), unbake=0.5, sky_gain=2.4, char_fill=(0.24, 0.26, 0.32)),
    "cityboss": dict(scene=12, pak="cityboss", blend="city-levels/cityboss/cityboss.blend", out="city-levels/cityboss/pass1", rules=BOSS_RULES, hand=BOSS_HAND,
                     look=BOSS_LOOK, hdri=None, hdri_rotation=0.0, hub=(-73.0, -73.0, 73.0, 72.0), game_sky=True, clutter=False,
                     materials=tuple(DEPT_TILES) + ("flat",), tiles=DEPT_TILES, detail=BOSS_DETAIL, tints={"d_tile": (1.7, 1.7, 1.7)},
                     captures=("city-levels/cityboss/world-hero.bin",), glow=BOSS_GLOW, hold=0.75, contrast=1.0, bloom_threshold=14.0),
    "westhub": dict(scene=13, pak="westhub", blend="westhub/westhub.blend", out="westhub/pass1", rules=WEST_RULES, hand=WEST_HAND,
                    look=WEST_LOOK, hdri=None, hdri_rotation=0.0, hub=(-70.0, -35.0, 72.0, 95.0), sky_panels=True, night_sky=False, clutter_opts=dict(leaves=0.0, pebbles=5.0, stones=0.7), island_boxes=True,
                    captures=("westhub/world-hero.bin", "westhub/world-sweep-a.bin", "westhub/world-sweep-b.bin", "westhub/world-sweep-c.bin"),
                    materials=tuple(WEST_TILES) + ("flat",), tiles=WEST_TILES, detail=WEST_DETAIL, binds={"ground": (("d_sand", 4, -1.0, 0.0),)},
                    solids=dict(cards={}, soft=tuple(f"westhub/textures/{n}" for n in ("cactus07", "cactus_bit", "cactus_bit2"))),
                    fog_color="#f4d8b0", ground_tint=(0.82, 0.62, 0.42), sky_gain=1.3, char_keep=0.55, tints={"d_sand": (2.0, 1.66, 1.05), "d_canyon": (1.8, 2.15, 2.5), "flat": (1.3, 0.86, 0.7)}),
}
