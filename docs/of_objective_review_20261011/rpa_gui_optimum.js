var cases=[{id:"gui_rp1_eps5",eps:5},{id:"gui_rp1_eps40",eps:40}];
for(var i=0;i<cases.length;i++){
 var c=cases[i];
 var cfg=new ConfigFile("C:/RPA-4.0.13/examples/A-1.cfg");
 var raw=JSON.parse(cfg.toString());
 raw.engineDefinition.chamberPressure={value:20,units:"bar"};
 raw.engineDefinition.bipropellantMixture={oxidizer:[{name:"O2(L)",massFraction:1}],fuel:[{name:"RP-1",massFraction:1}],mixtureRatio:{value:2.5,type:"OPTIMUM"}};
 raw.nozzleConditions.nozzleInletConditions={areaRatio:6.25};
 raw.nozzleConditions.nozzleExitConditions={areaRatio:c.eps};
 raw.nozzleConditions.equilibriumFlow={shifting:true};
 delete raw.thrustChamberSize;
 cfg.fromString(JSON.stringify(raw));
 var pa=new PropulsionAnalysis(cfg,false);var tp=pa.getPerformanceAnalysis();
 printf("AUTO_BEGIN %s\n",c.id);tp.printResults();
 var ex=tp.getNozzleExit();
 printf("AUTO_END %s %s\n",c.id,JSON.stringify({cstar:tp.getChamber().getCstar("m/s"),vac_isp_s:ex.getIs_v("s",false),delivered_vac_isp_s:ex.getIs_v("s",true),eps:ex.getAr()}));
}
