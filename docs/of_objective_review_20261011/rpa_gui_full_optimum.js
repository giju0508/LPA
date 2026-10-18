var epsValues=[5,40];
for(var i=0;i<epsValues.length;i++){
 var cfg=new ConfigFile("C:/RPA-4.0.13/examples/A-1.cfg"),raw=JSON.parse(cfg.toString());
 raw.engineDefinition.chamberPressure={value:20,units:"bar"};
 raw.engineDefinition.bipropellantMixture.mixtureRatio={value:2.5,type:"OPTIMUM"};
 raw.nozzleConditions.nozzleInletConditions={areaRatio:6.25};
 raw.nozzleConditions.nozzleExitConditions={areaRatio:epsValues[i]};
 raw.nozzleConditions.equilibriumFlow={shifting:true};
 raw.thrustChamberSize.sizing={numberOfChambers:1,throatDiameter:{value:20,units:"mm"}};
 raw.thrustChamberSize.nozzleGeometry={parabolicContour:{LeC15:80},RntoRt:.382};
 cfg.fromString(JSON.stringify(raw));var pa=new PropulsionAnalysis(cfg,false),tp=pa.getPerformanceAnalysis();
 printf("AUTO_BEGIN gui_full_eps%d\n",epsValues[i]);tp.printResults();
 var ex=tp.getNozzleExit();
 printf("AUTO_END gui_full_eps%d %s\n",epsValues[i],JSON.stringify({cstar:tp.getChamber().getCstar("m/s"),vac_isp_s:ex.getIs_v("s",false),delivered_vac_isp_s:ex.getIs_v("s",true),eps:ex.getAr()}));
}
