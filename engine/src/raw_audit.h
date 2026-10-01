// Test-only observations at LibRaw's real production callbacks. No callback is
// installed for normal preview/export. Early attenuation is an experiment, not
// a new recipe or supported production highlight policy.
#pragma once
#include <nlohmann/json.hpp>
#include <filesystem>
#include <stdexcept>
namespace pe {
struct RawAuditContext { std::string dir; double scale = 1; bool failed = false; uint32_t source_flip = 0; };
inline thread_local RawAuditContext *raw_audit_context = nullptr;
inline void raw_audit_checkpoint(void *ctx, const char *stage, bool attenuate) noexcept {
    auto *audit = raw_audit_context;
    if (!audit) return;
    try {
        auto &raw = *static_cast<LibRaw *>(ctx);
        const auto w=raw.imgdata.sizes.iwidth, h=raw.imgdata.sizes.iheight;
        const std::string path=audit->dir+"/"+stage;
        std::filesystem::create_directories(std::filesystem::u8path(audit->dir));
        FILE *f=utf8_fopen(path+".u16","wb");
        if (!f) throw std::runtime_error("raw audit open failed");
        const size_t count=size_t(w)*h*4;
        const bool complete=std::fwrite(raw.imgdata.image,sizeof(uint16_t),count,f)==count;
        std::fclose(f);if(!complete) throw std::runtime_error("raw audit write failed");
        nlohmann::json d={{"stage",stage},{"width",w},{"height",h},{"channels",4},
            {"sampleType","uint16"},{"byteOrder","little"},{"byteLength",count*2},
            {"rowStrideBytes",uint64_t(w)*8},{"orientationState","unrotated-decoder-frame"},
            {"sourceFlip",audit->source_flip},{"decoderCurrentFlip",raw.imgdata.sizes.flip},{"filters",raw.imgdata.idata.filters},
            {"channelOrder","decoder R G B G2 slots; sparse before interpolation"},
            {"alphaMode","no-alpha-plane"},{"primaries",std::string(stage)=="D3_post_rgb"?"sRGB":"camera-native; not an sRGB buffer"},
            {"transferFunction","linear decoder integers"},{"rangePolicy","uint16 [0,65535]; NOT scene-linear unbounded"},
            {"whiteLevel",raw.imgdata.color.maximum},{"blackLevel",raw.imgdata.color.black},
            {"cblack",{raw.imgdata.color.cblack[0],raw.imgdata.color.cblack[1],raw.imgdata.color.cblack[2],raw.imgdata.color.cblack[3]}},
            {"blackPatternSize",{raw.imgdata.color.cblack[4],raw.imgdata.color.cblack[5]}},
            {"librawVersion",LibRaw::version()},
            {"requestedUserMultipliers",{raw.imgdata.params.user_mul[0],raw.imgdata.params.user_mul[1],raw.imgdata.params.user_mul[2],raw.imgdata.params.user_mul[3]}},
            {"scaleAppliedAfterThisCheckpoint",attenuate?audit->scale:1.0},
            {"note","Real LibRaw callback in production raw_develop. Pre-scale is after black subtraction; sparse camera data is not an RGB display image."}};
        f=utf8_fopen(path+".json","wb");if(!f) throw std::runtime_error("raw descriptor open failed");
        const auto text=d.dump(2);const bool ok=std::fwrite(text.data(),1,text.size(),f)==text.size();std::fclose(f);
        if(!ok) throw std::runtime_error("raw descriptor write failed");
        if(attenuate && audit->scale!=1) {
            auto *pixels=reinterpret_cast<uint16_t*>(raw.imgdata.image);
            for(size_t i=0;i<count;++i) pixels[i]=uint16_t(pixels[i]*audit->scale);
        }
    } catch(...) {audit->failed=true;}
}
class AuditLibRaw : public LibRaw {
public:
    void enable_audit() {
        callbacks.pre_scalecolors_cb=[](void *p){raw_audit_checkpoint(p,"D0_pre_scale",true);};
        callbacks.pre_preinterpolate_cb=[](void *p){raw_audit_checkpoint(p,"D1_post_scale",false);};
        callbacks.pre_converttorgb_cb=[](void *p){raw_audit_checkpoint(p,"D2_pre_rgb",false);};
        callbacks.post_converttorgb_cb=[](void *p){raw_audit_checkpoint(p,"D3_post_rgb",false);};
    }
};
struct RawAuditScope {
    RawAuditContext *previous;
    explicit RawAuditScope(RawAuditContext *ctx):previous(raw_audit_context){raw_audit_context=ctx;}
    ~RawAuditScope(){raw_audit_context=previous;}
};
}
