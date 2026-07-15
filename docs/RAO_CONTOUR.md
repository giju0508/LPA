# Rao contour verification boundary

RPA 4 defines `theta_1` as the initial nozzle half-angle Tn and `theta_e` as
the exit half-angle Te (`RPA_4_User_Manual.pdf`, pp. 94 and 97). LPA uses the
same definitions, the conventional 15-degree conical reference length, a
circular throat blend, and a tangent-intersection quadratic parabola.

The automatic angle-selection algorithms are **not equivalent**. RPA's manual
documents Tn, Te, and relative length as configuration values but does not
publish the logic used when an angle is omitted. An RPA 4.0.13 check at
Ae/At = 14 with only `LeC15 = 80` returned Tn = 27.291945 degrees and
Te = 8.0 degrees. LPA's current empirical estimate for the same area and
length ratios returns Tn = 30.520318 degrees and Te = 10.629171 degrees.

NASA SP-125, figures 4-13 and 4-14, is the public reference for the standard
Rao parabolic approximation. Its worked Ae/At = 14, 80-percent-bell example
uses Tn = 27.4 degrees and Te = 9.8 degrees. This confirms the symbols and
construction, but it does not establish that RPA's unpublished automatic
defaults are a direct interpolation of that chart.

For that reason LPA does not label its estimated angles as RPA results.
Bell-contour metadata includes
`rao_angle_method = lpa_empirical_approximation_not_rpa`. Exact reproduction
of a particular RPA contour requires explicit Tn and Te inputs or a separately
validated, documented angle-selection policy.

Primary public reference: [NASA SP-125, Design of Liquid Propellant Rocket
Engines](https://ntrs.nasa.gov/citations/19710019929).
