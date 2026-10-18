// Run with the installed RPA 4 scripting utility, from its installation folder.
// Prints JSON only; does not save or modify a configuration or results file.
var propellant = {propellant: new Propellant(2.6), optimize: false};
propellant.propellant.addOxidizer("O2", 1);
propellant.propellant.addFuel("CH4", 1);
var performance = new TheoreticalPerformance(propellant, {
    pc: 10, pc_unit: "bar", ions: true, multiphase: false, condensed: false,
    solveNozzleFlow: true, nozzleInlet_Ar: 4, nozzleExit_Ar: 4
});
performance.assignCorrectionFactors(1, 1, 1, 1);
performance.solve(true);
var chamberDesign = new ChamberDesign({
    performance: performance, n: 1,
    sizing_type: "NOZZLE_THROAT_DIAMETER", Dt: 31.79, Dt_unit: "mm",
    pa: 0, pa_unit: "atm", length_type: "L_STAR", Lstar: 1000, Lstar_unit: "mm",
    b: 30, b_unit: "degrees", R1_to_Rt: 1.5, R2_to_R2max: 0.5
}, false);
var nozzleDesign = new NozzleDesign({
    chamberDesign: chamberDesign, type: "CONICAL",
    theta_e: 15, theta_e_unit: "degrees", R1_to_Rt: 0.382
});
var chamber = performance.getChamber();
var derivatives = chamber.getDerivatives("inj");
printf("BARTZ_REFERENCE %s\n", JSON.stringify({
    stagnation_temperature_k: chamber.getEquilibrium("inj").getT("K"),
    characteristic_velocity_m_s: chamber.getCstar("m/s"),
    frozen_specific_heat_j_kgk: derivatives.getCpfr("J/(kg K)"),
    frozen_prandtl: derivatives.getPrfr(),
    viscosity_pa_s: derivatives.getV("x10^-4 kg/(m s)") * 1e-4,
    gas_constant_j_kgk: derivatives.getR("J/(kg K)"),
    equilibrium_specific_heat_j_kgk: derivatives.getCpeql("J/(kg K)"),
    equilibrium_prandtl: derivatives.getPreql(),
    equilibrium_isentropic_exponent: derivatives.getK()
}));
var result = new HeatTransferAnalysis({
    chamberDesign: chamberDesign, nozzleDesign: nozzleDesign,
    throttle_value: 1, points: 60, applyCooling: false,
    Twg: 1000, Twg_unit: "K", approach: "BARTZ", wallLayer: 0.025,
    withRadiationHeatTransfer: false
}).getResults();
var stations = result.stations;
var throatIndex = 0;
for (var index = 1; index < stations.length; index++) {
    if (stations[index].r < stations[throatIndex].r) throatIndex = index;
}
var names = ["chamber", "throat", "exit"];
var selected = [0, throatIndex, stations.length - 1];
for (var index = 0; index < selected.length; index++) {
    var stationIndex = selected[index];
    var station = stations[stationIndex];
    var areaRatio = Math.pow(station.r / (0.03179 / 2), 2);
    var flow = performance.getNozzleStation(Math.max(1, areaRatio), "Ar",
                                           stationIndex >= throatIndex, false, true);
    printf("BARTZ_STATION %s\n", JSON.stringify({
        name: names[index], x_m: station.x, area_ratio: areaRatio,
        mach: flow.getMach(), actual_station_count: stations.length,
        heat_transfer_coefficient_w_m2k: station.alpha,
        convective_heat_flux_w_m2: station.q_conv
    }));
}
