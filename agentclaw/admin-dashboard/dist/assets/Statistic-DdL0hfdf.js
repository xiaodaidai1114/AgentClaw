import{af as S,C as r,H as c,I as T,v as a,al as u,J as _,aj as v,L as R,as as $,n as F}from"./index-Dv62bocw.js";function w(s){const{textColor2:e,textColor3:l,fontSize:n,fontWeight:i}=s;return{labelFontSize:n,labelFontWeight:i,valueFontWeight:i,valueFontSize:"24px",labelTextColor:l,valuePrefixTextColor:e,valueSuffixTextColor:e,valueTextColor:e}}const N={common:S,self:w},P=r("statistic",[c("label",`
 font-weight: var(--n-label-font-weight);
 transition: .3s color var(--n-bezier);
 font-size: var(--n-label-font-size);
 color: var(--n-label-text-color);
 `),r("statistic-value",`
 margin-top: 4px;
 font-weight: var(--n-value-font-weight);
 `,[c("prefix",`
 margin: 0 4px 0 0;
 font-size: var(--n-value-font-size);
 transition: .3s color var(--n-bezier);
 color: var(--n-value-prefix-text-color);
 `,[r("icon",{verticalAlign:"-0.125em"})]),c("content",`
 font-size: var(--n-value-font-size);
 transition: .3s color var(--n-bezier);
 color: var(--n-value-text-color);
 `),c("suffix",`
 margin: 0 0 0 4px;
 font-size: var(--n-value-font-size);
 transition: .3s color var(--n-bezier);
 color: var(--n-value-suffix-text-color);
 `,[r("icon",{verticalAlign:"-0.125em"})])])]),W=Object.assign(Object.assign({},v.props),{tabularNums:Boolean,label:String,value:[String,Number]}),j=T({name:"Statistic",props:W,slots:Object,setup(s){const{mergedClsPrefixRef:e,inlineThemeDisabled:l,mergedRtlRef:n}=_(s),i=v("Statistic","-statistic",P,N,s,e),f=R("Statistic",n,e),t=F(()=>{const{self:{labelFontWeight:x,valueFontSize:b,valueFontWeight:d,valuePrefixTextColor:m,labelTextColor:h,valueSuffixTextColor:g,valueTextColor:p,labelFontSize:z},common:{cubicBezierEaseInOut:C}}=i.value;return{"--n-bezier":C,"--n-label-font-size":z,"--n-label-font-weight":x,"--n-label-text-color":h,"--n-value-font-weight":d,"--n-value-font-size":b,"--n-value-prefix-text-color":m,"--n-value-suffix-text-color":g,"--n-value-text-color":p}}),o=l?$("statistic",void 0,t,s):void 0;return{rtlEnabled:f,mergedClsPrefix:e,cssVars:l?void 0:t,themeClass:o==null?void 0:o.themeClass,onRender:o==null?void 0:o.onRender}},render(){var s;const{mergedClsPrefix:e,$slots:{default:l,label:n,prefix:i,suffix:f}}=this;return(s=this.onRender)===null||s===void 0||s.call(this),a("div",{class:[`${e}-statistic`,this.themeClass,this.rtlEnabled&&`${e}-statistic--rtl`],style:this.cssVars},u(n,t=>a("div",{class:`${e}-statistic__label`},this.label||t)),a("div",{class:`${e}-statistic-value`,style:{fontVariantNumeric:this.tabularNums?"tabular-nums":""}},u(i,t=>t&&a("span",{class:`${e}-statistic-value__prefix`},t)),this.value!==void 0?a("span",{class:`${e}-statistic-value__content`},this.value):u(l,t=>t&&a("span",{class:`${e}-statistic-value__content`},t)),u(f,t=>t&&a("span",{class:`${e}-statistic-value__suffix`},t))))}});export{j as N};
