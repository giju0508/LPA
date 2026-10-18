# Coolant channel entry and transition method (0.17.0b1)

The previous coolant calculation applied fully developed rectangular laminar
Nu to every axial station and only warned about thermal entry using the whole
segment length. A cold RP-1 inlet could therefore cross the Re=2300 branch with
a large change in coolant convection. This revision evaluates a finite cell
average of the local developing-flow correlation, and connects the laminar
and turbulent endpoints over Re=2300 to 4000. It remains a screening model for
a rocket's varying-section, varying-property, conjugate rectangular channel.

## Primary references

1. Muzychka, Y. S. and Yovanovich, M. M. (2004), *Laminar Forced Convection
   Heat Transfer in the Combined Entry Region of Non-Circular Ducts*, Journal
   of Heat Transfer 126, 54–61, [DOI 10.1115/1.1643752](https://doi.org/10.1115/1.1643752).
   [Author-hosted full paper](https://www.mhtlab.uwaterloo.ca/pdf_papers/mhtl04-22.pdf),
   Eqs.12,21,22,42,43,45,46 and Table 1. Equations were checked against rendered
   original pages, including the positions of the square-root bars.
2. Gnielinski, V. (2013), *On heat transfer in tubes*, International Journal
   of Heat and Mass Transfer 63, 134–140,
   [DOI 10.1016/j.ijheatmasstransfer.2013.04.015](https://doi.org/10.1016/j.ijheatmasstransfer.2013.04.015).
   [Author's institutional record](https://publikationen.bibliothek.kit.edu/1000041280).
   The publisher's abstract explicitly describes interpolation between the
   laminar Re=2300 and turbulent Re=4000 values. Full-text access to this paper
   was unavailable during this audit; the rectangular endpoint substitution
   is an LPA adaptation, not reproduction of its circular laminar equation.
3. Gnielinski, V. (2010), *Heat Transfer in Pipe Flow*, VDI Heat Atlas,
   [DOI 10.1007/978-3-540-77877-6_34](https://doi.org/10.1007/978-3-540-77877-6_34).
   The conventional finite-length turbulent mean correction is
   `1 + (Dh/L)^(2/3)`. LPA analytically integrates the corresponding local
   correction over each cell; its use for rectangular conjugate channels is
   explicitly identified as an adaptation.

## Coordinates and units

`internal_flow_heat_transfer` accepts optional paired arguments:

- `distance_from_inlet_m`: nonnegative coolant heated path distance to the
  **cell inlet**, in m, increasing in coolant march order, including counterflow.
- `cell_length_m`: positive coolant path length through this cell, in m.
- `thermal_boundary_condition`: `conjugate` (default), `one_sided`,
  `uniform_heat_flux`, or `uniform_wall_temperature`.

Both lengths must be provided together. The distance is not gas-side axial
position, whole segment length, or distance measured backwards in counterflow.
The solver supplies the actual accumulated path and cell length. Linked serial
segments can carry entry distance only when their flow endpoints and section
are continuous; a new heated inlet restarts development. Section/property
changes within a circuit are treated with local properties and local geometry,
not a solved boundary-layer history. This assumption is reported as screening.

Calls without the new lengths keep the legacy fully developed laminar values
and emit an explicit missing-entry-distance warning. `heated_length_m` remains
available for old callers' entrance warnings, but does not replace the pair.
No external dependencies were added.

## Laminar local correlation and cell integral

Let `epsilon=min(width/height,height/width)`, `lambda=sqrt(A_one_channel)`,
`r=lambda/Dh=(1+epsilon)/(2*sqrt(epsilon))`,
`Re_lambda=r*Re_Dh`, and `z*=s/(Re_Dh*Pr*Dh*r^2)`.
The paper's friction factor is **Fanning**, not Darcy:

```
F = f_Fanning*Re_lambda
  = 12 / {sqrt(epsilon)*(1+epsilon)
           *[1-192*epsilon/pi^5*tanh(pi/(2*epsilon))]}

Nu_fd,lambda = C1*F / [8*sqrt(pi)*epsilon^gamma], gamma=1/10
```

The `epsilon^gamma` factor is outside `sqrt(pi)` in the original Eq.22/45.
For a circle, `r=sqrt(pi)/2`, `F=16*r`, and the shape factor is one.
For the local model, Table 1 gives `C2=C4=1`:

```
Nu_lambda(s) = [(f(Pr)/sqrt(z*))^m
                 + {(C3*(F/z*)^(1/3))^5 + Nu_fd,lambda^5}^(m/5)]^(1/m)
m = 2.27 + 1.65*Pr^(1/3)

UWF: C1=3.86, C3=0.501,
     f(Pr)=0.886/[1+(1.909*Pr^(1/6))^(9/2)]^(2/9)
UWT: C1=3.24, C3=0.409,
     f(Pr)=0.564/[1+(1.664*Pr^(1/6))^(9/2)]^(2/9)

Nu_cell,Dh = integral_a^(a+ds) Nu_lambda(s) ds / (r*ds)
h_cell = Nu_cell,Dh*k_bulk/Dh             [W/(m^2 K)]
```

The code integrates the **local** equation with 32-point Gauss-Legendre
quadrature and `s=a+ds*u^2`. The Jacobian cancels the first-cell `s^-1/2`
singularity, giving a finite, integrated first-cell value without an arbitrary
minimum inlet distance. Refining the inlet cell increases its average h as
expected, while the length-integrated Nu over a fixed channel is invariant
within quadrature error. Pointwise first-cell peak h is not mesh invariant.

This empirical combined-entry model's fully developed limit is its Eq.22
shape approximation, not the legacy exact rectangular Nu polynomial. For
example, UWF at epsilon=0.5 tends to Nu_Dh=4.5269327505; a circle tends to
4.35554 because of rounded C1, compared with the classical 4.364. In the
very thin epsilon=0.01 rectangular limit the upper-bound model gives 10.2147;
this must not be mistaken for the exact parallel-plate value near 8.235.
The source's reported comparisons do not establish a universal engine accuracy
bound. LPA reports these geometry and boundary adaptations as screening.

The reference requires `Pr >= 0.1`, `0.01 <= epsilon <= 1`, laminar forced
convection, uniform inlet profiles, constant section/properties and uniform
all-perimeter wall flux (UWF) or temperature (UWT). `conjugate`/`one_sided`
select UWF and explicitly warn about the different actual heated boundary.
Out-of-range Pr/aspect marks the result `unsupported` and returns the old
fully developed value solely as a diagnostic fallback. Finite input validation
still raises on invalid dimensions, properties, or entry coordinates.

## Transition, turbulent entry, and pressure loss

For `2300 < Re < 4000`, use

```
t = (Re-2300)/1700
Nu = (1-t)*Nu_lam(Re=2300,a,ds) + t*Nu_turb(Re=4000,a,ds)
```

This follows Gnielinski's endpoint interpolation interval, with the rectangular
combined-entry laminar endpoint substituted. Both endpoints are evaluated with
the same current cell properties/geometry and entry coordinates. The result is
continuous at both limits; it does not make actual transition onset universal.
A very short inlet cell can have a larger laminar endpoint than turbulent
endpoint. The resulting non-monotone interpolation gets an explicit validation
warning and stays `screening`; a small numerical cell alone is not an actual
correlation-domain violation.

For Gnielinski turbulent flow, the cell factor derived from the length-mean
entry correction is

```
a = distance_from_inlet_m; b = a + cell_length_m
entry_cell = 1 + Dh^(2/3)/[b^(2/3)+(a*b)^(1/3)+a^(2/3)]
```

It equals `1+(Dh/ds)^(2/3)` for the first cell and approaches the local factor
`1+(Dh/s)^(2/3)/3` downstream. Applying the cumulative length-mean correction
independently at every local station would count the inlet enhancement
repeatedly. Tests check partition invariance for this turbulent factor too.
Gnielinski Re above 5e6 or Pr outside 0.5–2000 is `unsupported`. Selecting
Dittus-Boelter does not silently inherit the Gnielinski entry factor; its
turbulent domain check remains Re>=10000 and 0.7<=Pr<=160.

In `internal_flow_heat_transfer`, Darcy f uses the legacy fully developed
rectangular Poiseuille polynomial below Re=2300, then a continuous linear
bridge from `Po/2300` to `f_Haaland(4000)` over the same transition interval.
The friction bridge is a stated numerical/hydraulic assumption, **not** a
Gnielinski pressure-loss correlation. Hydrodynamic entrance pressure loss is
not included, even though the laminar heat-transfer model includes combined
development. The standalone `darcy_friction_factor` API is unchanged.

No wall/bulk viscosity correction is added: hot wall properties can lie outside
the RP-1 surrogate validity range, and extrapolating them is not justified.
Two-phase boiling uses its phase-resolved model rather than automatically
inheriting single-phase thermal applicability from a precomputed helper.

## Verification

`tests/test_developing_channel_heat_transfer.py` checks finite first cells and
the independent flat-plate integral limit, reciprocal rectangular geometry,
classical circular limits, correct Eq.22 shape exponent, laminar/transition/
turbulent partition invariance at 12/120/700 cells, continuity of both Nu and
Darcy f at Re=2300 and 4000, explicit domain failures, boundary adaptation
warnings, and legacy calls. The mesh check holds properties and section fixed;
it verifies the cell integration, not convergence of a complete engine solution
with changing temperature, viscosity, geometry and wall resistance.
