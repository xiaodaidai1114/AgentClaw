import{ad as N,z as m,C as c,D as $,E as h,G as T,x as v,H as j,ah as _,aq as E,n as x,ai as I,K as V,ar as O,r as R,a as A,b$ as D,ba as F,am as K,ao as M,_ as U,u as q,o as d,b,j as G,c as f,w as p,F as J,k as Q,e as g,g as X,h as B,d as Y,c0 as Z,N as W,$ as ee,m as te}from"./index-Dmf-dwsc.js";import{N as re}from"./Select-Ckidvlih.js";const oe={fontWeightActive:"400"};function ae(e){const{fontSize:n,textColor3:a,textColor2:r,borderRadius:i,buttonColor2Hover:o,buttonColor2Pressed:s}=e;return Object.assign(Object.assign({},oe),{fontSize:n,itemLineHeight:"1.25",itemTextColor:a,itemTextColorHover:r,itemTextColorPressed:r,itemTextColorActive:r,itemBorderRadius:i,itemColorHover:o,itemColorPressed:s,separatorColor:a})}const ne={common:N,self:ae},se=m("breadcrumb",`
 white-space: nowrap;
 cursor: default;
 line-height: var(--n-item-line-height);
`,[c("ul",`
 list-style: none;
 padding: 0;
 margin: 0;
 `),c("a",`
 color: inherit;
 text-decoration: inherit;
 `),m("breadcrumb-item",`
 font-size: var(--n-font-size);
 transition: color .3s var(--n-bezier);
 display: inline-flex;
 align-items: center;
 `,[m("icon",`
 font-size: 18px;
 vertical-align: -.2em;
 transition: color .3s var(--n-bezier);
 color: var(--n-item-text-color);
 `),c("&:not(:last-child)",[$("clickable",[h("link",`
 cursor: pointer;
 `,[c("&:hover",`
 background-color: var(--n-item-color-hover);
 `),c("&:active",`
 background-color: var(--n-item-color-pressed); 
 `)])])]),h("link",`
 padding: 4px;
 border-radius: var(--n-item-border-radius);
 transition:
 background-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 color: var(--n-item-text-color);
 position: relative;
 `,[c("&:hover",`
 color: var(--n-item-text-color-hover);
 `,[m("icon",`
 color: var(--n-item-text-color-hover);
 `)]),c("&:active",`
 color: var(--n-item-text-color-pressed);
 `,[m("icon",`
 color: var(--n-item-text-color-pressed);
 `)])]),h("separator",`
 margin: 0 8px;
 color: var(--n-separator-color);
 transition: color .3s var(--n-bezier);
 user-select: none;
 -webkit-user-select: none;
 `),c("&:last-child",[h("link",`
 font-weight: var(--n-font-weight-active);
 cursor: unset;
 color: var(--n-item-text-color-active);
 `,[m("icon",`
 color: var(--n-item-text-color-active);
 `)]),h("separator",`
 display: none;
 `)])])]),S=I("n-breadcrumb"),ie=Object.assign(Object.assign({},_.props),{separator:{type:String,default:"/"}}),le=T({name:"Breadcrumb",props:ie,setup(e){const{mergedClsPrefixRef:n,inlineThemeDisabled:a}=j(e),r=_("Breadcrumb","-breadcrumb",se,ne,e,n);V(S,{separatorRef:O(e,"separator"),mergedClsPrefixRef:n});const i=x(()=>{const{common:{cubicBezierEaseInOut:s},self:{separatorColor:u,itemTextColor:t,itemTextColorHover:l,itemTextColorPressed:C,itemTextColorActive:k,fontSize:y,fontWeightActive:z,itemBorderRadius:P,itemColorHover:H,itemColorPressed:w,itemLineHeight:L}}=r.value;return{"--n-font-size":y,"--n-bezier":s,"--n-item-text-color":t,"--n-item-text-color-hover":l,"--n-item-text-color-pressed":C,"--n-item-text-color-active":k,"--n-separator-color":u,"--n-item-color-hover":H,"--n-item-color-pressed":w,"--n-item-border-radius":P,"--n-font-weight-active":z,"--n-item-line-height":L}}),o=a?E("breadcrumb",void 0,i,e):void 0;return{mergedClsPrefix:n,cssVars:a?void 0:i,themeClass:o==null?void 0:o.themeClass,onRender:o==null?void 0:o.onRender}},render(){var e;return(e=this.onRender)===null||e===void 0||e.call(this),v("nav",{class:[`${this.mergedClsPrefix}-breadcrumb`,this.themeClass],style:this.cssVars,"aria-label":"Breadcrumb"},v("ul",null,this.$slots))}});function ce(e=F?window:null){const n=()=>{const{hash:i,host:o,hostname:s,href:u,origin:t,pathname:l,port:C,protocol:k,search:y}=(e==null?void 0:e.location)||{};return{hash:i,host:o,hostname:s,href:u,origin:t,pathname:l,port:C,protocol:k,search:y}},a=R(n()),r=()=>{a.value=n()};return A(()=>{e&&(e.addEventListener("popstate",r),e.addEventListener("hashchange",r))}),D(()=>{e&&(e.removeEventListener("popstate",r),e.removeEventListener("hashchange",r))}),a}const de={separator:String,href:String,clickable:{type:Boolean,default:!0},showSeparator:{type:Boolean,default:!0},onClick:Function},ue=T({name:"BreadcrumbItem",props:de,slots:Object,setup(e,{slots:n}){const a=M(S,null);if(!a)return()=>null;const{separatorRef:r,mergedClsPrefixRef:i}=a,o=ce(),s=x(()=>e.href?"a":"span"),u=x(()=>o.value.href===e.href?"location":null);return()=>{const{value:t}=i;return v("li",{class:[`${t}-breadcrumb-item`,e.clickable&&`${t}-breadcrumb-item--clickable`]},v(s.value,{class:`${t}-breadcrumb-item__link`,"aria-current":u.value,href:e.href,onClick:e.onClick},n),e.showSeparator&&v("span",{class:`${t}-breadcrumb-item__separator`,"aria-hidden":"true"},K(n.separator,()=>{var l;return[(l=e.separator)!==null&&l!==void 0?l:r.value]})))}}}),me={class:"page-header"},he={class:"header-left"},ve={key:1},be={key:1},fe={__name:"PageHeader",props:{title:{type:String,default:""},breadcrumbs:{type:Array,default:()=>[]},showTimeSelector:{type:Boolean,default:!1},showRefresh:{type:Boolean,default:!0},defaultTime:{type:String,default:"24h"}},emits:["time-change","refresh"],setup(e){const a=R(e.defaultTime),{t:r}=q(),i=x(()=>[{label:r("pageHeader.time24h"),value:"24h"},{label:r("pageHeader.time7d"),value:"7d"},{label:r("pageHeader.time30d"),value:"30d"}]);return(o,s)=>{const u=ee("router-link");return d(),b("header",me,[G("div",he,[e.breadcrumbs.length?(d(),f(g(le),{key:0},{default:p(()=>[(d(!0),b(J,null,Q(e.breadcrumbs,(t,l)=>(d(),f(g(ue),{key:l},{default:p(()=>[t.to?(d(),f(u,{key:0,to:t.to},{default:p(()=>[X(B(t.text),1)]),_:2},1032,["to"])):(d(),b("span",ve,B(t.text),1))]),_:2},1024))),128))]),_:1})):(d(),b("h2",be,B(e.title),1))]),Y(g(W),{class:"header-right",size:12,align:"center"},{default:p(()=>[Z(o.$slots,"actions",{},()=>[e.showTimeSelector?(d(),f(g(re),{key:0,value:a.value,"onUpdate:value":[s[0]||(s[0]=t=>a.value=t),s[1]||(s[1]=t=>o.$emit("time-change",t))],options:i.value,style:{width:"150px"},size:"small"},null,8,["value","options"])):te("",!0)],!0)]),_:3})])}}},xe=U(fe,[["__scopeId","data-v-7c4882e4"]]);export{xe as P};
