"""
Known Venues with Coordinates for Essen
Used as fallback when geocoding fails or no address is provided
"""

KNOWN_VENUES = {
    # Zollverein venues
    "zollverein": {"lat": 51.4864, "lon": 7.0403, "address": "Gelsenkirchener Str. 181, 45309 Essen"},
    "ruhr museum": {"lat": 51.4864, "lon": 7.0403, "address": "Gelsenkirchener Str. 181, 45309 Essen"},
    "red dot": {"lat": 51.4857, "lon": 7.0378, "address": "Klemmannstr. 3, 45329 Essen"},
    "halle 8": {"lat": 51.4829, "lon": 7.0325, "address": "Kronprinzenstr. 8, 45128 Essen"},
    "pact": {"lat": 51.4848, "lon": 7.0389, "address": "Bullmannaue 11, 45329 Essen"},
    "stiftung zollverein": {"lat": 51.4864, "lon": 7.0403, "address": "Gelsenkirchener Str. 181, 45309 Essen"},
    "unesco-welterbe zollverein": {"lat": 51.4864, "lon": 7.0403, "address": "Gelsenkirchener Str. 181, 45309 Essen"},

    # theaters
    "lichtburg": {"lat": 51.4549, "lon": 7.0136, "address": "Lichtburg Essen, Kettwiger Str. 36, 45127 Essen"},
    "grillo-theater": {"lat": 51.4516, "lon": 7.0133, "address": "Friedrichstr. 55, 45128 Essen"},
    "grillo theater": {"lat": 51.4516, "lon": 7.0133, "address": "Friedrichstr. 55, 45128 Essen"},
    "aalto-theater": {"lat": 51.4469, "lon": 7.0127, "address": "Aalto-Theater, Opernplatz 10, 45128 Essen"},
    "stadtpark": {"lat": 51.4891, "lon": 7.0105, "address": "Stadtpark 1, 45131 Essen"},
    "zeche carl": {"lat": 51.4965, "lon": 7.0124, "address": "Zeche Carl, Wilhelm-Nieswandt-Allee 100, 45326 Essen-Altenessen"},
    "villa hügel": {"lat": 51.4069, "lon": 7.0090, "address": "Villa Hügel, Hügel 1, 45133 Essen-Bredeney"},
    "maschinenhaus": {"lat": 51.4965, "lon": 7.0124, "address": "Maschinenhaus Essen, Wilhelm-Nieswandt-Allee 100, 45326 Essen-Altenessen"},
    "studio-bühne": {"lat": 51.4651, "lon": 7.0962, "address": "Studio-Bühne Essen, Korumhöhe 11, 45307 Essen-Kray"},
    "studio bühne": {"lat": 51.4651, "lon": 7.0962, "address": "Studio-Bühne Essen, Korumhöhe 11, 45307 Essen-Kray"},
    "studio-buehne": {"lat": 51.4651, "lon": 7.0962, "address": "Studio-Bühne Essen, Korumhöhe 11, 45307 Essen-Kray"},
    "weststadthalle": {"lat": 51.4438, "lon": 7.0632, "address": "Weststadthalle, Bebelplatz 1, 45128 Essen"},
    "philharmonie": {"lat": 51.4516, "lon": 7.0133, "address": "Philharmonie Essen, Huyssenallee 41, 45128 Essen"},
    "goethebunker": {"lat": 51.4567, "lon": 7.0098, "address": "Goethebunker, 45128 Essen"},
    "turock": {"lat": 51.4615, "lon": 7.0138, "address": "Turock, Viehofer Platz 3, 45127 Essen"},
    "rabbit hole": {"lat": 51.4617, "lon": 7.0145, "address": "Rabbit Hole Theater, Viehofer Platz 19, 45127 Essen"},
    "theater courage": {"lat": 51.4388, "lon": 7.0023, "address": "Theater Courage, Goethestr. 67, 45130 Essen-Rüttenscheid"},
    "courage": {"lat": 51.4388, "lon": 7.0023, "address": "Theater Courage, Goethestr. 67, 45130 Essen-Rüttenscheid"},
    "atelierhaus": {"lat": 51.4587, "lon": 7.0142, "address": "Atelierhaus Schützenbahn, Schützenbahn 19, 45127 Essen"},
    "schützenbahn": {"lat": 51.4587, "lon": 7.0142, "address": "Atelierhaus Schützenbahn, Schützenbahn 19, 45127 Essen"},

    # museums
    "folkwang": {"lat": 51.4473, "lon": 7.0593, "address": "Goethestr. 41, 45128 Essen"},

    # parks
    "grugapark": {"lat": 51.4293, "lon": 7.0561, "address": "Virchowstr. 4, 45147 Essen"},
    "gruga": {"lat": 51.4293, "lon": 7.0561, "address": "Grugapark, Virchowstr. 4, 45147 Essen"},
    "grugahalle": {"lat": 51.4293, "lon": 7.0561, "address": "Grugahalle, Virchowstr. 4, 45147 Essen"},

    # other venues
    "kulturforum": {"lat": 51.4364, "lon": 7.0193, "address": "Kulturforum Steele, 45276 Essen"},
    "tck": {"lat": 51.4638, "lon": 7.0125, "address": "Turnclub 1888 Essen e.V., 45128 Essen"},

    # frequently-seen venues from real sync data (added 2026-06)
    "dance4water": {"lat": 51.4503, "lon": 7.0220, "address": "Dance4Water, Friedrich-Ebert-Str. 23, 45127 Essen"},
    "grend kulturzentrum": {"lat": 51.4376, "lon": 7.0816, "address": "GREND Kulturzentrum, Westfalenstr. 311, 45276 Essen"},
    "grendtheater": {"lat": 51.4376, "lon": 7.0816, "address": "GRENDTheater, Westfalenstr. 311, 45276 Essen"},
    "grend": {"lat": 51.4376, "lon": 7.0816, "address": "GREND Kulturzentrum, Westfalenstr. 311, 45276 Essen"},
    "freak show": {"lat": 51.4602, "lon": 7.0148, "address": "FREAK SHOW Rock'n'Roll Bar, Heinickestr. 8, 45128 Essen"},
    "szene 10": {"lat": 51.4543, "lon": 7.0050, "address": "Szene 10 - Bühne im Girardet, Hindenburgstr. 67, 45127 Essen"},
    "girardet": {"lat": 51.4543, "lon": 7.0050, "address": "Girardethaus, Hindenburgstr. 67, 45127 Essen"},
    "orbit": {"lat": 51.4513, "lon": 7.0107, "address": "Orbit (Schalthaus 2), 45127 Essen"},
    "schalthaus": {"lat": 51.4513, "lon": 7.0107, "address": "Schalthaus 2, 45127 Essen"},
    "seaside beach baldeney": {"lat": 51.3977, "lon": 7.0361, "address": "Seaside Beach Baldeneysee, Freiherr-vom-Stein-Str. 386a, 45133 Essen"},
    "seaside beach": {"lat": 51.3977, "lon": 7.0361, "address": "Seaside Beach Baldeneysee, 45133 Essen"},
    "essen metro": {"lat": 51.4280, "lon": 7.0660, "address": "Metro Essen, Norbertstr. 100, 45131 Essen"},
    "drive in autokino": {"lat": 51.4280, "lon": 7.0660, "address": "DRIVE IN Autokino, Sulterkamp 70, 45356 Essen"},
    "autokino essen": {"lat": 51.5020, "lon": 6.9970, "address": "Autokino Essen, Sulterkamp 70, 45356 Essen"},
    "om club": {"lat": 51.4543, "lon": 7.0070, "address": "OM Club, Vereinsstr. 14, 45127 Essen"},
    "faces bar": {"lat": 51.4543, "lon": 7.0080, "address": "FACES Bar, 45127 Essen"},
    "gentlem": {"lat": 51.4543, "lon": 7.0080, "address": "gentleM Essen, 45127 Essen"},
    "cozycourt": {"lat": 51.4543, "lon": 7.0090, "address": "CozyCourt Essen, 45127 Essen"},
    "kula yoga": {"lat": 51.4543, "lon": 7.0090, "address": "Kula Yoga Studio, 45127 Essen"},
    "ikea essen": {"lat": 51.4170, "lon": 7.0860, "address": "IKEA Essen, Frohnhauser Str. 297, 45144 Essen"},
    "hirschlandplatz": {"lat": 51.4534, "lon": 7.0156, "address": "Hirschlandplatz, 45127 Essen"},
    "donnerberg": {"lat": 51.3838, "lon": 7.0411, "address": "Donnerberg, 45239 Essen"},
    "bonnekamphöhe": {"lat": 51.5043, "lon": 7.0530, "address": "Naturgarten Bonnekamphöhe, Bonnekampstr., 45327 Essen"},
    "bonnekamphoehe": {"lat": 51.5043, "lon": 7.0530, "address": "Naturgarten Bonnekamphöhe, Bonnekampstr., 45327 Essen"},
    "adolf-clarenbach-kirche": {"lat": 51.3870, "lon": 7.0470, "address": "Adolf-Clarenbach-Kirche, Heisinger Str., 45239 Essen-Heisingen"},
    "st. gertrud": {"lat": 51.4564, "lon": 7.0135, "address": "St. Gertrud, Rottstr., 45127 Essen"},
    "zeche bonifacius": {"lat": 51.4570, "lon": 7.0980, "address": "Zeche Bonifacius, Schurenbachstr., 45329 Essen"},
    "umformerhalle": {"lat": 51.4570, "lon": 7.0980, "address": "Umformerhalle Zeche Bonifacius, 45329 Essen"},
    "co-working praxis": {"lat": 51.4543, "lon": 7.0100, "address": "Co-Working Praxis ZEITRAUMplus, 45127 Essen"},
    "zeitraumplus": {"lat": 51.4543, "lon": 7.0100, "address": "ZEITRAUMplus, 45127 Essen"},
    "denkmal steile lagerung": {"lat": 51.4864, "lon": 7.0403, "address": "Denkmal Steile Lagerung, Zollverein, 45309 Essen"},

    # new venues added 2026-06 (verified via OSM/Nominatim)
    "albert-schweitzer-tierheim": {"lat": 51.4696, "lon": 7.0093, "address": "Albert-Schweitzer-Tierheim, Grillostr. 24, 45141 Essen"},
    "tierheim essen": {"lat": 51.4696, "lon": 7.0093, "address": "Albert-Schweitzer-Tierheim, Grillostr. 24, 45141 Essen"},
    "essen hauptbahnhof": {"lat": 51.4515, "lon": 7.0133, "address": "Essen Hauptbahnhof, 45127 Essen"},
    "messe essen": {"lat": 51.4287, "lon": 6.9944, "address": "Messe Essen, Messeplatz, 45131 Essen"},
    "domschatzkammer": {"lat": 51.4557, "lon": 7.0139, "address": "Domschatzkammer, Burgplatz 2, 45127 Essen"},
    "domschatz essen": {"lat": 51.4557, "lon": 7.0139, "address": "Domschatzkammer, Burgplatz 2, 45127 Essen"},
    "kunsthaus essen": {"lat": 51.4258, "lon": 7.0532, "address": "Kunsthaus Essen, Rübezahlstr. 33, 45134 Essen-Rellinghausen"},
    "katakomben-theater": {"lat": 51.4308, "lon": 7.0062, "address": "Katakomben Theater, Steile Str. 1, 45147 Essen"},
    "katakomben theater": {"lat": 51.4308, "lon": 7.0062, "address": "Katakomben Theater, Steile Str. 1, 45147 Essen"},
    "neoliet": {"lat": 51.4479, "lon": 6.9870, "address": "Boulderbar Neoliet, Münchener Str. 106a, 45145 Essen-Holsterhausen"},
    "element boulders": {"lat": 51.4553, "lon": 6.9854, "address": "Element Boulders Essen, Haedenkampstr. 73, 45143 Essen-Altendorf"},
    "hespertalbahn": {"lat": 51.3883, "lon": 7.0618, "address": "Hespertalbahn, Kupferdreh, 45257 Essen"},
    "ruhrverband kläranlage kupferdreh": {"lat": 51.3943, "lon": 7.0787, "address": "Ruhrverband Kläranlage Essen-Kupferdreh, Kampmannbrücke 11, 45257 Essen"},
    "musikpalette": {"lat": 51.4537, "lon": 7.0131, "address": "Musikpalette (MuPa), Kettwiger Str. 20, 45127 Essen"},
    "neue musik zentrale": {"lat": 51.4617, "lon": 7.0147, "address": "Neue Musik Zentrale, Viehofer Platz 18, 45127 Essen"},
}


def find_known_venue(venue_name: str, title: str = "") -> dict | None:
    """
    Check if the venue or title contains a known venue name.
    Returns dict with lat, lon, address if found.
    """
    search_text = f"{venue_name or ''} {title or ''}".lower()

    for keyword, coords in KNOWN_VENUES.items():
        if keyword in search_text:
            return coords

    return None
