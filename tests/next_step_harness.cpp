// Local preview/core experiment harness. Uses production C ABI and render path.
#include "photo_engine.h"
#include "engine_impl.h"
#include "cancel_flag.h"
#include "sha256.h"
#include <libraw/libraw.h>
#include <nlohmann/json.hpp>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <cmath>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <psapi.h>
#endif
using namespace pe;
using J=nlohmann::json;
double ms(){return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now().time_since_epoch()).count();}
std::string read(const std::string&p){std::ifstream f(std::filesystem::u8path(p));std::ostringstream s;s<<f.rdbuf();return s.str();}
void save(const std::string&p,const void*data,size_t n){std::ofstream f(std::filesystem::u8path(p),std::ios::binary);f.write(static_cast<const char*>(data),n);if(!f)throw std::runtime_error("write failed");}
J timer(const StageTimings&t){return {{"read",t.read_ms},{"unpack",t.unpack_ms},{"rawProcess",t.raw_process_ms},
 {"rawConvert",t.raw_convert_ms},{"orientation",t.orientation_ms},{"exposure",t.exposure_ms},
 {"transferEncode",t.transfer_encode_ms},{"look",t.look_ms},{"transferDecode",t.transfer_decode_ms},
 {"geometry",t.geometry_ms},{"resize",t.resize_ms},{"finalEncode",t.encode_prep_ms},
 {"diagnostic",t.diagnostic_ms},{"cacheCopy",t.cache_copy_ms},{"pipelineTotal",t.total_ms}};}
int main(int argc,char**argv){try{
 if(argc!=6){std::cerr<<"next_step_harness session|headroom SOURCE LOOK RECIPE OUTDIR\n";return 2;}
 const std::string mode=argv[1],path=argv[2],lookpath=argv[3],outdir=argv[5];
 std::filesystem::create_directories(outdir);
 J recipe=J::parse(read(argv[4]));
 pe_engine *engine=nullptr;pe_source *source=nullptr;
 std::string config=J({{"configVersion",1},{"assetSearchPaths",{lookpath}}}).dump();
 const double openstart=ms();
 if(pe_engine_create(config.data(),config.size(),&engine)!=PE_OK)return 3;
 auto st=pe_source_open_local(engine,path.data(),path.size(),&source);
 if(st!=PE_OK)return 4;
 const double openms=ms()-openstart;
 if(mode=="decode-only") {
  LibRaw raw;int opened=raw.open_file(path.c_str());int unpacked=opened==0?raw.unpack():opened;
  std::cout<<J({{"open_status",opened},{"unpack_status",unpacked},{"wb_resolved",false},
      {"cam_mul",{raw.imgdata.color.cam_mul[0],raw.imgdata.color.cam_mul[1],raw.imgdata.color.cam_mul[2],raw.imgdata.color.cam_mul[3]}},
      {"note","No RGB develop attempted and no gains fabricated"}}).dump()<<std::endl;
  pe_source_release(source);pe_engine_destroy(engine);return unpacked==0?0:1;
 }
 auto*core=reinterpret_cast<Engine*>(engine);auto*src=reinterpret_cast<Source*>(source);
 std::string line;
 while(std::getline(std::cin,line)){
  const J command=J::parse(line);J r=recipe;
  r["look"]["amount"]=command.value("amount",0.0);
  if(command.contains("lookOverride")) for(auto it=command["lookOverride"].begin();it!=command["lookOverride"].end();++it) r["look"][it.key()]=it.value();
  r["adjustments"]["exposureEV"]=command.value("ev",0.0);
  const double wb=command.value("wbFactor",1.0);
  if(wb!=1){r["adjustments"]["whiteBalance"]["mode"]="custom";r["adjustments"]["whiteBalance"]["resolvedCameraMultipliers"][0]=r["adjustments"]["whiteBalance"]["resolvedCameraMultipliers"][0].get<double>()*wb;}
  if(command.contains("rotation"))r["geometry"]["rotationQuarterTurns"]=command["rotation"];
  if(command.contains("mirror"))r["geometry"]["flipHorizontal"]=command["mirror"];
  const std::string body=r.dump(),name=command.at("name"),prefix=outdir+"/"+name;
  save(prefix+".recipe.json",body.data(),body.size());
  J result={{"name",name},{"sourceOpenMs",openms},{"recipeSha256",sha256_hex(reinterpret_cast<const uint8_t*>(body.data()),body.size())}};
  if(mode=="headroom"){
   RecipeModel model;LookPackage look;std::string error;
   int code=prepare_recipe(*core,*src,body.data(),body.size(),model,look,error);
   if(code)throw std::runtime_error(error);
   RenderRequest request=make_render_request(model,look,0,prefix.c_str());request.collect_diagnostics=true;
   request.audit_early_scale=command.value("earlyScale",1.0);
   StageTimings timings;RenderOutput output;
   bool ok=render_to_pixels(path,request,core->limits,nullptr,output,timings,code,error);
   result["status"]=code;result["error"]=error;result["timingsMs"]=timer(timings);result["earlyScale"]=request.audit_early_scale;
   if(ok){result["width"]=output.out_width;result["height"]=output.out_height;}
  }else{
   pe_cancel_token*cancel=nullptr;pe_cancel_create(&cancel);
   std::string cancelAt=command.value("cancelAt",std::string());
   if(!cancelAt.empty())reinterpret_cast<CancelFlag*>(cancel)->set_observer([](CancelFlag&f,const char*stage,void*p) noexcept{
    if(stage && *static_cast<std::string*>(p)==stage)f.request();
   },&cancelAt);
   pe_preview_options opt{sizeof(pe_preview_options),1,command.value("longEdge",1200u),0,command.value("generation",uint64_t(0))};
   pe_image*image=nullptr;const auto before=src->preview_cache.develops;const auto hits=src->preview_cache.hits;
   const double begin=ms();
   st=pe_render_preview(engine,source,body.data(),body.size(),&opt,cancel,&image);
   result["wallRenderMs"]=ms()-begin;result["status"]=st;result["cacheHit"]=src->preview_cache.hits>hits;
   result["developCountDelta"]=src->preview_cache.develops-before;result["developCountTotal"]=src->preview_cache.develops;
   result["cacheHitsTotal"]=src->preview_cache.hits;result["cacheMissesTotal"]=src->preview_cache.misses;
   result["timingsMs"]=st==PE_OK?timer(src->preview_cache.last_timings):J(nullptr);
   if(st==PE_OK){
    pe_image_info info{};info.struct_size=sizeof(info);info.abi_version=1;pe_image_describe(image,&info);
    const auto*px=static_cast<const float*>(info.pixels);const size_t n=size_t(info.width)*info.height;
    bool alpha=true;for(size_t i=0;i<n;++i)alpha=alpha && px[i*4+3]==1;
    result["alphaAllOne"]=alpha;result["width"]=info.width;result["height"]=info.height;
    result["orientationState"]=info.orientation_state;result["generation"]=info.request_generation;
    const double diag=ms();
    result["pixelSha256"]=sha256_hex(static_cast<const uint8_t*>(info.pixels),info.byte_length);
    save(prefix+".rgba.f32",info.pixels,info.byte_length);
    std::vector<uint8_t> rgb(n*3);for(size_t i=0;i<n;++i)for(int c=0;c<3;++c)rgb[i*3+c]=uint8_t(std::floor(std::max(0.f,std::min(1.f,px[i*4+c]))*255+.5f));
    const std::string header="P6\n"+std::to_string(info.width)+" "+std::to_string(info.height)+"\n255\n";
    std::ofstream ppm(prefix+".ppm",std::ios::binary);ppm<<header;ppm.write(reinterpret_cast<const char*>(rgb.data()),rgb.size());ppm.close();
    result["diagnosticWriteHashMs"]=ms()-diag;
    if(command.value("verifyUncached",false)){
     RecipeModel m;LookPackage look;std::string error;int code=prepare_recipe(*core,*src,body.data(),body.size(),m,look,error);
     if(code)throw std::runtime_error(error);
     auto req=make_render_request(m,look,opt.long_edge_px);RenderOutput uncached;StageTimings t;
     if(!render_to_pixels(path,req,core->limits,nullptr,uncached,t,code,error))throw std::runtime_error(error);
     double diff=0;for(size_t i=0;i<n;++i)for(int c=0;c<3;++c)diff=std::max(diff,double(std::abs(px[i*4+c]-uncached.encoded.data[i*3+c])));
     result["uncachedMaxAbs"]=diff;result["uncachedShapeEqual"]=uncached.out_width==info.width && uncached.out_height==info.height;
    }
    pe_image_release(image);
   }else{result["imageIsNull"]=image==nullptr;pe_blob*b=nullptr;pe_last_error_json(engine,&b);size_t len;const auto*data=pe_blob_data(b,&len);result["error"]=std::string(reinterpret_cast<const char*>(data),len);pe_blob_release(b);}
   pe_cancel_release(cancel);
   if(command.value("export",false)){
    const std::string output=prefix+".jpg";const double begin=ms();
    result["exportStatus"]=pe_export_jpeg(engine,source,body.data(),body.size(),output.data(),output.size(),nullptr);
    result["exportWallMs"]=ms()-begin;result["exportCacheDevelopsUnchanged"]=src->preview_cache.develops==before+(result["developCountDelta"].get<uint64_t>());
   }
  }
#ifdef _WIN32
  PROCESS_MEMORY_COUNTERS_EX mem{};mem.cb=sizeof(mem);GetProcessMemoryInfo(GetCurrentProcess(),reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&mem),sizeof(mem));
  result["processLifetimePeakWorkingSetBytes"]=mem.PeakWorkingSetSize;result["workingSetBytes"]=mem.WorkingSetSize;
#endif
  const auto record=result.dump(2);save(prefix+".json",record.data(),record.size());std::cout<<result.dump()<<std::endl;
 }
 pe_source_release(source);pe_engine_destroy(engine);return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
