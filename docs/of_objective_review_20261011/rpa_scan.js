function run(eps,mr){
 var p={propellant:new Propellant(mr),optimize:false};p.propellant.addOxidizer("O2(L)",1);p.propellant.addFuel("RP-1",1);
 var c={pc:20,pc_unit:"bar",ions:true,multiphase:true,condensed:false,solveNozzleFlow:true,nozzleInlet_Ar:6.25,nozzleExit_Ar:eps};
 var t=new TheoreticalPerformance(p,c);t.solve(false);
 var e=t.getNozzleExit();
 return {mr:mr,eps:eps,cstar:t.getChamber().getCstar("m/s"),vac_isp_s:e.getIs_v("s",false),delivered_vac_isp_s:e.getIs_v("s",true),opt_isp_s:e.getIs("s",false),sea_isp_s:e.getIs_H(1,"atm","s",false)};
}
for(var k=0;k<2;k++){
 var eps=k==0?5:40;
 for(var i=0;i<=60;i++){printf("SCAN %s\n",JSON.stringify(run(eps,1.8+i*.025)));}
 var keys=["cstar","vac_isp_s","delivered_vac_isp_s","opt_isp_s"];
 if(eps==5)keys.push("sea_isp_s");
 for(var j=0;j<keys.length;j++){
  var key=keys[j],a=1.8,b=3.3,g=(Math.sqrt(5)-1)/2;
  var x1=b-g*(b-a),x2=a+g*(b-a),r1=run(eps,x1),r2=run(eps,x2);
  for(var n=0;n<30;n++){
   if(r1[key]<r2[key]){a=x1;x1=x2;r1=r2;x2=a+g*(b-a);r2=run(eps,x2);}
   else{b=x2;x2=x1;r2=r1;x1=b-g*(b-a);r1=run(eps,x1);}
  }
  printf("MAXIMUM %s\n",JSON.stringify({eps:eps,objective:key,result:r1[key]>r2[key]?r1:r2}));
 }
}
