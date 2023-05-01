import stream_gears
import argparse
import json

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input', type=str, required=True)
    parser.add_argument('-o', '--output', type=str, default='')
    parser.add_argument('-s', '--segment', type=int, default=3600)
    parser.add_argument('--header', type=str, default=r'{}')
    args = parser.parse_args()

    class Segment(): 
        pass; 
    
    segment = Segment(); 
    segment.time=args.segment; 
    try:
        header = json.loads(args.header)
    except:
        header = {}
    try:
        stream_gears.download(
            args.input,
            header,
            args.output,
            segment
        )
    except KeyboardInterrupt:
        exit(0)