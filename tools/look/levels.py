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
                    lumps=dict(roles=("snow",), density=0.3, colour="#f4f9ff"), sky_gain=1.35, ground_tint=(0.74, 0.67, 0.59), tints={"snowfield": (0.8, 0.82, 0.86)}),
}
