var config = {
    videoname : 'DanmuLayer',
    width : 1920,
    height : 1080,
    pixelaspect : 1.00,
    videoDuration : 'auto',
    framerate : 30,
    danmurate : 0.5,
    overflow_operate : 'override',
    opacity : 100,

    font : 'MicrosoftYaHei-Bold',
    fontsize : 30,
    margin : 6,
    dmDuration : 10,
    dmDistance: 0.33,
}

function DanmuItem(text,color,start_time){
    this.text = text;
    this.color = color;
    this.start_time = start_time;
    this.dmDuration = config.dmDuration;
    this.length = text.length*config.fontsize;
}

function DanmuTrack(startheight,height){
    this.startheight = startheight;
    this.height = height;
    this.width = config.width;
    this.dlist = [];
    this.latest = null;
    this.length = 0;
    
    this.append = function(danmu){
        this.dlist.push(danmu);
        this.latest = danmu;
        this.length += 1;
    }
    this.latest_bias = function(timestamp){
        if(!this.latest){
            return this.width;
        }
        var latest = this.latest;
        var time_cost = timestamp-latest.start_time
        if(time_cost>latest.dmDuration){
            return this.width;
        }
        var bias = time_cost/latest.dmDuration*(this.width+latest.length);
        return bias;
    }
}

function DanmuCompound(){
    this.config = config;
    this.tracks = [];
    this.dmcnt = 0;

    var danmuheight = this.config.height*this.config.danmurate;
    var trackheight = this.config.fontsize+this.config.margin;
    this.tracknum = Math.floor(danmuheight/trackheight);
    for(var i=0;i<this.tracknum;i++){
        var track = new DanmuTrack(i*trackheight,trackheight);
        this.tracks.push(track);
    }

    this.add = function(danmu){
        var pos = -1;
        var maxbias = -1;
        var overflow = true;

        for(var i=0;i<this.tracknum;i++){
            var bias = this.tracks[i].latest_bias(danmu.start_time);
            if(bias>this.config.width*config.dmDistance){
                pos = i;
                maxbias = bias;
                overflow = false;
                break;
            }
            if(bias>maxbias){
                maxbias = bias;
                pos = i;
            }
        }

        if(overflow && this.config.overflow_operate == 'ignore'){
            return;
        }
        
        this.dmcnt += 1;
        this.tracks[pos].append(danmu);
    }

    this.render = function(){
        render(this);
    }
}

function render(dmcomp){
    proj = app.project
    if(proj == null){
        proj = app.newProject();
    }
    if(config.videoDuration == 'auto'){
        duration = config.dmDuration;
        for(var t=0;t<dmcomp.tracknum;t++){
            latest = dmcomp.tracks[t].latest;
            if(latest == null){
                continue;
            }
            if((latest.start_time+config.dmDuration)>duration){
                duration = latest.start_time+config.dmDuration
            }
        }
        config.videoDuration = duration;
    }
    comp = proj.items.addComp(config.videoname,
                              config.width,
                              config.height,
                              config.pixelaspect,
                              config.videoDuration,
                              config.framerate
                            )
    
    //render
    var id_list = new Array();
    for(var i=0;i<dmcomp.tracknum;i++){
        id_list.push(0);
    }
    for(var i=0;i<dmcomp.dmcnt;i++){
        var item = null;
        var time = 10800;
        var trackid = 0;
        for(var t=0;t<dmcomp.tracknum;t++){
            if(id_list[t]<dmcomp.tracks[t].length){
                id = id_list[t];
                dm = dmcomp.tracks[t].dlist[id];
                if(dm.start_time<time){
                    item = dm;
                    time = dm.start_time;
                    trackid = t;
                }
            }
        }
        id_list[trackid] += 1;
        var track = dmcomp.tracks[trackid];

        var starttime = item.start_time;
        var endtime = item.start_time+item.dmDuration;
        var startpos = [track.width,track.startheight+track.height];
        var endpos = [-item.length,track.startheight+track.height];

        danmulayer = comp.layers.addText(item.text);
        var textProp = danmulayer.property("Source Text");
        var textDocument = textProp.value;
        textDocument.resetCharStyle();
        textDocument.font = config.font;
        textDocument.fontSize = config.fontsize;
        textDocument.fillColor = item.color;
        textDocument.strokeWidth = 1;
        textDocument.strokeColor = [0, 0, 0];
        textDocument.applyStroke = true;
        textDocument.strokeOverFill = false;
        textProp.setValue(textDocument);

        danmulayer.inPoint = starttime;
        danmulayer.outPoint = endtime;
        
        danmulayer.position.setValueAtTime(starttime,startpos)
        danmulayer.position.setValueAtTime(endtime,endpos)

        danmulayer.property("Opacity").setValue(config.opacity)

    }

}

